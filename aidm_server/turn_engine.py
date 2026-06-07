from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from flask import current_app

from aidm_server.action_intent import apply_action_intent_to_rule_hint
from aidm_server.canon_jobs import enqueue_canon_job, process_canon_job
from aidm_server.database import db
from aidm_server.emergent_memory import refresh_session_projection
from aidm_server.llm import CONTEXT_VERSION, build_dm_context
from aidm_server.logging_context import set_logging_context
from aidm_server.models import Campaign, CampaignSegment, DmTurn, Player, Session, safe_json_dumps, safe_json_loads
from aidm_server.rules import RuleHint, classify_player_action
from aidm_server.segment_triggers import evaluate_segment_trigger, parse_trigger_spec
from aidm_server.socket_contracts import (
    dm_chunk_payload,
    dm_response_end_payload,
    dm_response_start_payload,
    new_message_payload,
    roll_required_payload,
    segment_triggered_payload,
    session_log_update_payload,
    socket_error_payload as socket_error,
    turn_duplicate_payload,
    turn_status_payload,
)
from aidm_server.telemetry import telemetry_event, telemetry_metric, telemetry_timing
from aidm_server.text_sanitization import ReasoningBlockFilter, strip_reasoning_blocks
from aidm_server.time_utils import utc_now
from aidm_server.turn_coordinator import session_turn_coordinator
from aidm_server.turn_events import (
    DM_RESPONSE_EVENT,
    PLAYER_MESSAGE_EVENT,
    ROLL_RESOLVED_EVENT,
    SEGMENT_TRIGGERED_EVENT,
    record_turn_event,
)
from aidm_server.turn_rules import (
    apply_pending_resolution_hint as default_apply_pending_resolution_hint,
    build_roll_prompt as default_build_roll_prompt,
    dc_hint_from_turn as default_dc_hint_from_turn,
    latest_pending_turn as default_latest_pending_turn,
    pending_turn_by_id as default_pending_turn_by_id,
    response_mentions_roll_request as default_response_mentions_roll_request,
)


logger = logging.getLogger(__name__)


@dataclass
class TurnCommand:
    sid: str
    session_id: int
    campaign_id: int
    world_id: int
    player_id: int
    user_input: str
    manual_segment_ids: set[int]
    action_intent: dict | None = None
    client_message_id: str | None = None


class TurnEngine:
    def __init__(
        self,
        *,
        socketio,
        emit_fn: Callable,
        stream_fn: Callable,
        latest_pending_turn_fn: Callable[[int, int | None], DmTurn | None] | None = None,
        pending_turn_by_id_fn: Callable[[int, int, int | None], DmTurn | None] | None = None,
        dc_hint_from_turn_fn: Callable[[DmTurn | None], str | None] | None = None,
        apply_pending_resolution_hint_fn: Callable[[int, int, RuleHint, int | None], tuple[DmTurn | None, int | None]] | None = None,
        build_roll_prompt_fn: Callable[[RuleHint, int | None], str] | None = None,
        response_mentions_roll_request_fn: Callable[[str], bool] | None = None,
    ):
        self.socketio = socketio
        self.emit = emit_fn
        self.stream_fn = stream_fn
        self.latest_pending_turn = latest_pending_turn_fn or default_latest_pending_turn
        self.pending_turn_by_id = pending_turn_by_id_fn or default_pending_turn_by_id
        self.dc_hint_from_turn = dc_hint_from_turn_fn or default_dc_hint_from_turn
        self.apply_pending_resolution_hint = apply_pending_resolution_hint_fn or default_apply_pending_resolution_hint
        self.build_roll_prompt = build_roll_prompt_fn or default_build_roll_prompt
        self.response_mentions_roll_request = response_mentions_roll_request_fn or default_response_mentions_roll_request

    @staticmethod
    def _is_admin_override(action_intent: dict | None) -> bool:
        return isinstance(action_intent, dict) and action_intent.get('kind') == 'admin'

    @staticmethod
    def _admin_model_input(user_input: str) -> str:
        clean = str(user_input or '').strip()
        for prefix in ('[ADMIN]', '/admin'):
            if clean.lower().startswith(prefix.lower()):
                clean = clean[len(prefix):].strip()
                break
        return (
            'ADMIN OVERRIDE (authenticated):\n'
            f'{clean}\n\n'
            'This is an out-of-character table administrator directive. Make it happen in the next DM response. '
            'Do not ask for a roll, do not defer the outcome, and do not refuse due to normal story uncertainty. '
            'If the directive changes established state, make the change true and give a concise in-world explanation.'
        )

    @staticmethod
    def _interaction_model_input(user_input: str, action_intent: dict | None, actor_label: str) -> str:
        if not isinstance(action_intent, dict) or action_intent.get('kind') != 'interact':
            return user_input
        interaction = action_intent.get('interaction') if isinstance(action_intent.get('interaction'), dict) else {}
        target = action_intent.get('target') if isinstance(action_intent.get('target'), dict) else {}
        target_character = str(target.get('character_name') or 'another player character').strip()
        target_player = str(target.get('player_name') or '').strip()
        interaction_type = str(interaction.get('type') or 'act_on').strip()
        interaction_labels = {
            'speak_to': 'speak to the target',
            'act_on': 'take an action directed at the target',
            'give_to': 'give something to the target',
            'take_from': 'try to take something from the target',
        }
        clean_input = str(user_input or '').strip()
        target_player_line = f'\nTarget player profile: {target_player}' if target_player else ''
        return (
            'PLAYER-TO-PLAYER INTERACTION:\n'
            f'Acting character: {actor_label}\n'
            f'Target character: {target_character}'
            f'{target_player_line}\n'
            f'Interaction intent: {interaction_labels.get(interaction_type, "interact with the target")}\n\n'
            'Player message:\n'
            f'{clean_input}\n\n'
            'DM handling: Treat the target as a player character in this campaign, even if they have not spoken in '
            'the current chat log yet. Keep the acting character and target character distinct. Resolve the speech '
            'or action as directed at the target, ask for a roll when the action needs one, and do not narrate the '
            "target player's voluntary response for them."
        )

    @classmethod
    def _model_input_for_action(cls, user_input: str, action_intent: dict | None, actor_label: str) -> str:
        if cls._is_admin_override(action_intent):
            return cls._admin_model_input(user_input)
        if isinstance(action_intent, dict) and action_intent.get('kind') == 'interact':
            return cls._interaction_model_input(user_input, action_intent, actor_label)
        return user_input

    @staticmethod
    def _player_is_available_for_campaign(player: Player | None, campaign: Campaign) -> bool:
        if not player:
            return False
        if player.workspace_id:
            return player.workspace_id == campaign.workspace_id
        return player.campaign_id == campaign.campaign_id

    def _prepare_interaction_target(self, command: TurnCommand, campaign: Campaign) -> bool:
        action_intent = command.action_intent
        if not isinstance(action_intent, dict) or action_intent.get('kind') != 'interact':
            return True
        target = action_intent.get('target')
        target_player_id = target.get('player_id') if isinstance(target, dict) else None
        target_player = db.session.get(Player, target_player_id) if isinstance(target_player_id, int) else None
        if not self._player_is_available_for_campaign(target_player, campaign):
            self.emit(
                'error',
                socket_error(
                    'interaction_target_invalid',
                    'Target player is not available in this workspace.',
                    {'target_player_id': target_player_id},
                ),
            )
            telemetry_event(
                'socket.send_message.interaction_target_invalid',
                payload={
                    'sid': command.sid,
                    'session_id': command.session_id,
                    'player_id': command.player_id,
                    'target_player_id': target_player_id,
                    'campaign_id': campaign.campaign_id,
                },
                severity='warning',
            )
            return False
        target['character_name'] = target_player.character_name
        target['player_name'] = target_player.name
        return True

    def process(self, command: TurnCommand):
        with session_turn_coordinator.serialized(command.session_id) as wait_ms:
            if wait_ms >= 1.0:
                telemetry_timing(
                    'socket.turn_queue_wait_ms',
                    wait_ms,
                    tags={'session_id': command.session_id, 'campaign_id': command.campaign_id},
                )
            return self._process_serialized(command)

    def _process_serialized(self, command: TurnCommand):
        session_obj = db.session.get(Session, command.session_id)
        if not session_obj:
            self.emit('error', socket_error('session_not_found', 'Session not found'))
            telemetry_event(
                'socket.send_message.session_not_found',
                payload={'sid': command.sid, 'session_id': command.session_id},
                severity='warning',
            )
            return

        if session_obj.campaign_id != command.campaign_id:
            self.emit('error', socket_error('campaign_mismatch', 'Session does not belong to this campaign'))
            telemetry_event(
                'socket.send_message.campaign_mismatch',
                payload={'sid': command.sid, 'session_id': command.session_id, 'campaign_id': command.campaign_id},
                severity='warning',
            )
            return

        campaign = db.session.get(Campaign, command.campaign_id)
        if not campaign:
            self.emit('error', socket_error('campaign_not_found', 'Campaign not found'))
            telemetry_event(
                'socket.send_message.campaign_not_found',
                payload={'sid': command.sid, 'campaign_id': command.campaign_id},
                severity='warning',
            )
            return

        player = db.session.get(Player, command.player_id)
        if not player:
            self.emit('error', socket_error('invalid_player', 'Invalid player ID'))
            telemetry_event(
                'socket.send_message.invalid_player',
                payload={'sid': command.sid, 'player_id': command.player_id},
                severity='warning',
            )
            return

        if not self._player_is_available_for_campaign(player, campaign):
            self.emit('error', socket_error('campaign_mismatch', 'Player is not available in this workspace'))
            telemetry_event(
                'socket.send_message.campaign_mismatch',
                payload={'sid': command.sid, 'player_id': command.player_id, 'campaign_id': command.campaign_id},
                severity='warning',
            )
            return

        if not self._prepare_interaction_target(command, campaign):
            return

        player_label = player.character_name
        is_admin_override = self._is_admin_override(command.action_intent)
        rules_engine_enabled = bool(current_app.config.get('AIDM_RULES_ENGINE_ENABLED', True))
        rule_hint: RuleHint = (
            classify_player_action(command.user_input)
            if rules_engine_enabled
            else RuleHint(
                requires_roll=False,
                roll_type=None,
                dc_hint=None,
                reason='Rules engine disabled',
                confidence=1.0,
                roll_value=None,
                outcome_deferred=False,
            )
        )
        rule_hint = apply_action_intent_to_rule_hint(command.action_intent, rule_hint)

        if command.client_message_id:
            duplicate_turn = (
                DmTurn.query.filter(
                    DmTurn.session_id == command.session_id,
                    DmTurn.player_id == command.player_id,
                    DmTurn.metadata_json.contains(f'"client_message_id": "{command.client_message_id}"'),
                )
                .order_by(DmTurn.turn_id.desc())
                .first()
            )
            if duplicate_turn:
                self.emit(
                    'turn_duplicate',
                    turn_duplicate_payload(
                        command.session_id,
                        duplicate_turn.turn_id,
                        command.client_message_id,
                    ),
                )
                self.emit(
                    'session_log_update',
                    session_log_update_payload(command.session_id, duplicate_turn.turn_id),
                    room=str(command.session_id),
                )
                telemetry_event(
                    'socket.send_message.duplicate_ignored',
                    payload={
                        'sid': command.sid,
                        'session_id': command.session_id,
                        'player_id': command.player_id,
                        'client_message_id': command.client_message_id,
                    },
                )
                return

        roll_target_pending_turn_id = None
        if command.action_intent and command.action_intent.get('kind') == 'roll':
            raw_roll = command.action_intent.get('roll')
            if isinstance(raw_roll, dict):
                roll_target_pending_turn_id = raw_roll.get('target_pending_turn_id')

        pending_turn_before = None
        if not is_admin_override:
            pending_turn_before = (
                self.pending_turn_by_id(command.session_id, command.player_id, roll_target_pending_turn_id)
                if roll_target_pending_turn_id is not None
                else self.latest_pending_turn(command.session_id, command.player_id)
            )
        if roll_target_pending_turn_id is not None and rule_hint.roll_value is not None and not pending_turn_before:
            self.emit(
                'error',
                socket_error(
                    'pending_roll_target_not_found',
                    'The selected pending check is no longer available. Refresh and choose another target.',
                    {
                        'session_id': command.session_id,
                        'pending_turn_id': roll_target_pending_turn_id,
                    },
                ),
            )
            telemetry_event(
                'socket.send_message.pending_roll_target_not_found',
                payload={
                    'sid': command.sid,
                    'session_id': command.session_id,
                    'player_id': command.player_id,
                    'pending_turn_id': roll_target_pending_turn_id,
                },
                severity='warning',
            )
            return

        if pending_turn_before and rule_hint.roll_value is None:
            pending_rule_type = pending_turn_before.rule_type or 'check'
            pending_dc_hint = self.dc_hint_from_turn(pending_turn_before)
            roll_required = roll_required_payload(
                session_id=command.session_id,
                pending_turn_id=pending_turn_before.turn_id,
                rule_type=pending_rule_type,
                dc_hint=pending_dc_hint,
                prompt=self.build_roll_prompt(
                    RuleHint(
                        requires_roll=True,
                        roll_type=pending_rule_type,
                        dc_hint=pending_dc_hint,
                        reason='Pending roll required',
                        confidence=1.0,
                        roll_value=None,
                        outcome_deferred=True,
                    ),
                    pending_turn_id=pending_turn_before.turn_id,
                ),
            )
            self.emit('roll_required', roll_required)
            self.emit(
                'error',
                socket_error(
                    'roll_required',
                    'Resolve the pending check before taking a new action.',
                    roll_required,
                ),
            )
            telemetry_event(
                'socket.send_message.roll_required',
                payload={
                    'sid': command.sid,
                    'session_id': command.session_id,
                    'pending_turn_id': pending_turn_before.turn_id,
                    'rule_type': pending_rule_type,
                },
                severity='warning',
            )
            return

        if not is_admin_override and rule_hint.roll_value is not None and not pending_turn_before:
            any_pending_turn = self.latest_pending_turn(command.session_id, None)
            if any_pending_turn is not None and any_pending_turn.player_id != command.player_id:
                self.emit(
                    'error',
                    socket_error(
                        'pending_roll_not_owned',
                        'Another player has the unresolved check. Your roll cannot resolve it.',
                        {
                            'session_id': command.session_id,
                            'pending_turn_id': any_pending_turn.turn_id,
                            'pending_player_id': any_pending_turn.player_id,
                        },
                    ),
                )
                telemetry_event(
                    'socket.send_message.pending_roll_not_owned',
                    payload={
                        'sid': command.sid,
                        'session_id': command.session_id,
                        'player_id': command.player_id,
                        'pending_turn_id': any_pending_turn.turn_id,
                        'pending_player_id': any_pending_turn.player_id,
                    },
                    severity='warning',
                )
                return

        pending_turn_to_resolve, resolved_turn_id = self.apply_pending_resolution_hint(
            command.session_id,
            command.player_id,
            rule_hint,
            roll_target_pending_turn_id,
        )
        rules_hint_payload = {
            'requires_roll': rule_hint.requires_roll,
            'roll_type': rule_hint.roll_type,
            'dc_hint': rule_hint.dc_hint,
            'reason': rule_hint.reason,
            'confidence': rule_hint.confidence,
            'roll_value': rule_hint.roll_value,
            'outcome_deferred': rule_hint.outcome_deferred,
            'resolved_turn_id': resolved_turn_id,
            'target_pending_turn_id': roll_target_pending_turn_id,
        }

        turn = DmTurn(
            session_id=command.session_id,
            campaign_id=command.campaign_id,
            player_id=command.player_id,
            player_input=command.user_input,
            requires_roll=rule_hint.requires_roll,
            rule_type=rule_hint.roll_type,
            confidence=rule_hint.confidence,
            roll_value=rule_hint.roll_value,
            outcome_status='deferred' if rule_hint.outcome_deferred else 'resolved',
            rules_hint=safe_json_dumps(rules_hint_payload, {}),
            context_version=CONTEXT_VERSION,
            status='processing',
            metadata_json=safe_json_dumps(
                {
                    'speaker': player_label,
                    'resolved_turn_id': resolved_turn_id,
                    'action_intent': command.action_intent,
                    'client_message_id': command.client_message_id,
                },
                {},
            ),
        )

        start_time = time.perf_counter()
        incoming_save_started = time.perf_counter()
        if not self._persist_incoming_turn(turn, player_label, command, rule_hint, pending_turn_to_resolve, resolved_turn_id):
            return
        self._record_phase_timing(
            'incoming_db_save',
            incoming_save_started,
            campaign_id=command.campaign_id,
            session_id=command.session_id,
        )
        self._emit_turn_status(command.session_id, turn.turn_id, 'received')

        self.emit(
            'new_message',
            new_message_payload(
                message=command.user_input,
                speaker=player_label,
                turn_id=turn.turn_id,
                requires_roll=rule_hint.requires_roll,
                rules_hint=rules_hint_payload,
                context_version=CONTEXT_VERSION,
                action_intent=command.action_intent,
                client_message_id=command.client_message_id,
            ),
            room=str(command.session_id),
            include_self=False,
        )

        triggered_segments = self._evaluate_segments(
            turn=turn,
            campaign=campaign,
            command=command,
            allowed_trigger_types={'keywords'},
            include_manual=False,
        )
        for segment_payload in triggered_segments:
            self.emit('segment_triggered', segment_payload, room=str(command.session_id))

        dm_response_text, stream_error = self._narrate_turn(
            turn=turn,
            campaign=campaign,
            player_label=player_label,
            world_id=campaign.world_id,
            user_input=command.user_input,
            model_user_input=self._model_input_for_action(command.user_input, command.action_intent, player_label),
            rules_hint_payload=rules_hint_payload,
            resolved_turn_id=resolved_turn_id,
        )

        # Keep the per-session coordinator locked until the DM response has a
        # durable DmTurn row and timeline event. Canon extraction can continue
        # asynchronously after that saved boundary.
        self._emit_turn_status(command.session_id, turn.turn_id, 'saving')
        post_turn_segments = self._persist_turn_outcome(
            turn=turn,
            campaign=campaign,
            command=command,
            player_label=player_label,
            rules_hint_payload=rules_hint_payload,
            dm_response_text=dm_response_text,
            stream_error=stream_error,
            triggered_segments=triggered_segments,
            start_time=start_time,
        )
        for segment_payload in post_turn_segments:
            self.socketio.emit('segment_triggered', segment_payload, room=str(command.session_id))

        self.socketio.emit(
            'session_log_update',
            session_log_update_payload(command.session_id, turn.turn_id),
            room=str(command.session_id),
        )

    def _background_post_turn(
        self,
        app,
        *,
        turn: DmTurn,
        campaign: Campaign,
        command: TurnCommand,
        player_label: str,
        rules_hint_payload: dict,
        dm_response_text: str,
        stream_error: str | None,
        triggered_segments: list[dict],
        start_time: float,
    ):
        with app.app_context():
            # Re-attach ORM objects to the new session so lazy loads work.
            turn = db.session.merge(turn)
            campaign = db.session.merge(campaign)
            self._emit_turn_status(command.session_id, turn.turn_id, 'saving')

            post_turn_segments = self._persist_turn_outcome(
                turn=turn,
                campaign=campaign,
                command=command,
                player_label=player_label,
                rules_hint_payload=rules_hint_payload,
                dm_response_text=dm_response_text,
                stream_error=stream_error,
                triggered_segments=triggered_segments,
                start_time=start_time,
            )
            for segment_payload in post_turn_segments:
                self.socketio.emit('segment_triggered', segment_payload, room=str(command.session_id))

            self.socketio.emit(
                'session_log_update',
                session_log_update_payload(command.session_id, turn.turn_id),
                room=str(command.session_id),
            )

    def _emit_turn_status(self, session_id: int, turn_id: int | None, status: str, details: dict | None = None):
        self.socketio.emit('turn_status', turn_status_payload(session_id, turn_id, status, details), room=str(session_id))

    @staticmethod
    def _record_phase_timing(
        phase: str,
        started_at: float,
        *,
        campaign_id: int,
        session_id: int,
    ) -> None:
        telemetry_timing(
            'socket.turn_phase_latency_ms',
            float((time.perf_counter() - started_at) * 1000),
            tags={'campaign_id': campaign_id, 'phase': phase, 'session_id': session_id},
        )

    def _persist_incoming_turn(
        self,
        turn: DmTurn,
        player_label: str,
        command: TurnCommand,
        rule_hint: RuleHint,
        pending_turn_to_resolve: DmTurn | None,
        resolved_turn_id: int | None,
    ) -> bool:
        try:
            db.session.add(turn)
            db.session.flush()
            set_logging_context(turn_id=turn.turn_id)

            if pending_turn_to_resolve:
                pending_turn_to_resolve.outcome_status = 'resolved'
                pending_metadata = safe_json_loads(pending_turn_to_resolve.metadata_json, {})
                pending_metadata['resolved_by_turn_id'] = turn.turn_id
                pending_metadata['resolved_at'] = utc_now().isoformat()
                pending_turn_to_resolve.metadata_json = safe_json_dumps(pending_metadata, {})
                record_turn_event(
                    session_id=command.session_id,
                    campaign_id=command.campaign_id,
                    turn_id=turn.turn_id,
                    player_id=command.player_id,
                    event_type=ROLL_RESOLVED_EVENT,
                    payload={
                        'pending_turn_id': pending_turn_to_resolve.turn_id,
                        'roll_value': rule_hint.roll_value,
                        'metadata': {
                            'turn_id': turn.turn_id,
                            'resolved_turn_id': pending_turn_to_resolve.turn_id,
                            'roll_value': rule_hint.roll_value,
                            'rule_type': rule_hint.roll_type,
                            'action_intent': command.action_intent,
                            'client_message_id': command.client_message_id,
                        },
                    },
                )

            record_turn_event(
                session_id=command.session_id,
                campaign_id=command.campaign_id,
                turn_id=turn.turn_id,
                player_id=command.player_id,
                event_type=PLAYER_MESSAGE_EVENT,
                payload={
                    'message': command.user_input,
                    'speaker': player_label,
                    'metadata': {
                        'turn_id': turn.turn_id,
                        'confidence': rule_hint.confidence,
                        'outcome_status': turn.outcome_status,
                        'resolved_turn_id': resolved_turn_id,
                        'action_intent': command.action_intent,
                        'client_message_id': command.client_message_id,
                    },
                },
            )
            db.session.commit()
            return True
        except Exception as exc:
            db.session.rollback()
            logger.error('Failed to persist incoming player turn: %s', str(exc))
            self.emit('error', socket_error('turn_persist_failed', 'Failed to persist player action.'))
            telemetry_event(
                'socket.send_message.turn_persist_failed',
                payload={'sid': command.sid, 'session_id': command.session_id},
                severity='error',
            )
            return False

    def _segment_state_payload(self, session_id: int, campaign: Campaign) -> tuple[dict, dict]:
        session_state = refresh_session_projection(session_id, campaign)
        session_state_payload = {
            'current_location': session_state.current_location,
            'current_quest': session_state.current_quest,
        }
        campaign_state = {
            'location': campaign.location,
            'current_quest': campaign.current_quest,
        }
        return session_state_payload, campaign_state

    def _activate_segments(
        self,
        *,
        turn: DmTurn,
        session_id: int,
        segments_to_activate: list[tuple[CampaignSegment, dict]],
    ) -> list[dict]:
        triggered_segments: list[dict] = []
        for seg, payload in segments_to_activate:
            seg.is_triggered = True
            triggered_segments.append(payload)
            record_turn_event(
                session_id=session_id,
                campaign_id=turn.campaign_id,
                turn_id=turn.turn_id,
                player_id=turn.player_id,
                event_type=SEGMENT_TRIGGERED_EVENT,
                payload={
                    'title': seg.title,
                    'reason': payload.get('reason'),
                    'segment_id': seg.segment_id,
                    'metadata': {'turn_id': turn.turn_id, 'reason': payload.get('reason')},
                },
            )
        return triggered_segments

    def _evaluate_segments(
        self,
        turn: DmTurn,
        campaign: Campaign,
        command: TurnCommand,
        *,
        allowed_trigger_types: set[str] | None,
        include_manual: bool,
    ) -> list[dict]:
        triggered_segments: list[dict] = []
        automatic_enabled = bool(current_app.config.get('AIDM_SEGMENT_EVALUATOR_ENABLED', True))
        if not (automatic_enabled or (include_manual and command.manual_segment_ids)):
            return triggered_segments

        try:
            segments_to_activate: list[tuple[CampaignSegment, dict]] = []
            if automatic_enabled:
                session_state_payload, campaign_state = self._segment_state_payload(command.session_id, campaign)
                untriggered_segments = CampaignSegment.query.filter_by(
                    campaign_id=command.campaign_id,
                    is_triggered=False,
                ).all()

                for seg in untriggered_segments:
                    trigger_type = parse_trigger_spec(seg.trigger_condition).trigger_type
                    if trigger_type == 'manual':
                        continue
                    if allowed_trigger_types is not None and trigger_type not in allowed_trigger_types:
                        continue
                    matched, reason, trigger_spec = evaluate_segment_trigger(
                        trigger_condition=seg.trigger_condition,
                        player_message=command.user_input,
                        session_state=session_state_payload,
                        campaign_state=campaign_state,
                    )
                    if not matched:
                        continue

                    payload = segment_triggered_payload(
                        segment_id=seg.segment_id,
                        title=seg.title,
                        description=seg.description,
                        reason=reason,
                        trigger_spec=trigger_spec,
                    )
                    segments_to_activate.append((seg, payload))

            if include_manual and command.manual_segment_ids:
                manual_segments = (
                    CampaignSegment.query.filter(
                        CampaignSegment.campaign_id == command.campaign_id,
                        CampaignSegment.segment_id.in_(command.manual_segment_ids),
                        CampaignSegment.is_triggered.is_(False),
                    ).all()
                )
                for seg in manual_segments:
                    payload = segment_triggered_payload(
                        segment_id=seg.segment_id,
                        title=seg.title,
                        description=seg.description,
                        reason='manual_override',
                        trigger_spec={'trigger_type': 'manual', 'raw': {'source': 'client_override'}},
                    )
                    if not any(existing.segment_id == seg.segment_id for existing, _payload in segments_to_activate):
                        segments_to_activate.append((seg, payload))

            triggered_segments = self._activate_segments(
                turn=turn,
                session_id=command.session_id,
                segments_to_activate=segments_to_activate,
            )
            db.session.commit()
            if triggered_segments:
                telemetry_metric('socket.segment_triggered_total', len(triggered_segments))
        except Exception as exc:
            db.session.rollback()
            logger.error('Segment evaluation failed: %s', str(exc))
            telemetry_event(
                'socket.segment_evaluation_failed',
                payload={'session_id': command.session_id, 'campaign_id': command.campaign_id, 'error': str(exc)},
                severity='error',
            )
            return []

        return triggered_segments

    def _narrate_turn(
        self,
        *,
        turn: DmTurn,
        campaign: Campaign,
        player_label: str,
        world_id: int,
        user_input: str,
        model_user_input: str,
        rules_hint_payload: dict,
        resolved_turn_id: int | None,
    ) -> tuple[str, str | None]:
        context_started = time.perf_counter()
        context = build_dm_context(world_id, campaign.campaign_id, turn.session_id, query_text=user_input)
        self._record_phase_timing(
            'context_build',
            context_started,
            campaign_id=campaign.campaign_id,
            session_id=turn.session_id,
        )
        self._emit_turn_status(turn.session_id, turn.turn_id, 'narrating')
        telemetry_event(
            'socket.dm_stream_started',
            payload={
                'session_id': turn.session_id,
                'campaign_id': campaign.campaign_id,
                'turn_id': turn.turn_id,
                'provider': current_app.config.get('AIDM_LLM_PROVIDER'),
                'model': current_app.config.get('AIDM_LLM_MODEL'),
                'context_version': CONTEXT_VERSION,
            },
        )
        self.emit(
            'dm_response_start',
            dm_response_start_payload(
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                requires_roll=turn.requires_roll,
                rules_hint=rules_hint_payload,
                context_version=CONTEXT_VERSION,
            ),
            room=str(turn.session_id),
        )

        dm_response_text = ''
        stream_error = None
        reasoning_filter = ReasoningBlockFilter()
        provider_started = time.perf_counter()
        first_token_recorded = False
        try:
            for chunk in self.stream_fn(
                model_user_input,
                context,
                speaking_player={'character_name': player_label, 'player_id': str(turn.player_id)},
                rules_hint=rules_hint_payload,
            ):
                if not chunk:
                    continue
                if not first_token_recorded:
                    self._record_phase_timing(
                        'provider_time_to_first_token',
                        provider_started,
                        campaign_id=campaign.campaign_id,
                        session_id=turn.session_id,
                    )
                    first_token_recorded = True
                chunk = reasoning_filter.filter(chunk)
                if not chunk:
                    continue
                self.emit(
                    'dm_chunk',
                    dm_chunk_payload(
                        chunk=chunk,
                        session_id=turn.session_id,
                        turn_id=turn.turn_id,
                        requires_roll=turn.requires_roll,
                        rules_hint=rules_hint_payload,
                        context_version=CONTEXT_VERSION,
                    ),
                    room=str(turn.session_id),
                )
                self.socketio.sleep(0)
                dm_response_text += chunk
            final_chunk = reasoning_filter.finish()
            if final_chunk:
                self.emit(
                    'dm_chunk',
                    dm_chunk_payload(
                        chunk=final_chunk,
                        session_id=turn.session_id,
                        turn_id=turn.turn_id,
                        requires_roll=turn.requires_roll,
                        rules_hint=rules_hint_payload,
                        context_version=CONTEXT_VERSION,
                    ),
                    room=str(turn.session_id),
                )
                self.socketio.sleep(0)
                dm_response_text += final_chunk
        except Exception as exc:
            stream_error = str(exc)
            logger.error('Error generating streamed DM response: %s', stream_error)
            self.emit('error', socket_error('dm_generation_failed', 'Error generating DM response', {'detail': stream_error}))
            telemetry_event(
                'socket.dm_generation_failed',
                payload={'session_id': turn.session_id, 'turn_id': turn.turn_id, 'error': stream_error},
                severity='error',
            )
        finally:
            self._record_phase_timing(
                'provider_total',
                provider_started,
                campaign_id=campaign.campaign_id,
                session_id=turn.session_id,
            )

        if turn.requires_roll and turn.roll_value is None and not self.response_mentions_roll_request(dm_response_text):
            injected_prompt = self.build_roll_prompt(
                RuleHint(
                    requires_roll=True,
                    roll_type=turn.rule_type,
                    dc_hint=safe_json_loads(turn.rules_hint, {}).get('dc_hint'),
                    reason='Roll prompt injected',
                    confidence=turn.confidence or 1.0,
                    roll_value=None,
                    outcome_deferred=True,
                ),
                pending_turn_id=resolved_turn_id,
            )
            injected_chunk = f'\n\n{injected_prompt}' if dm_response_text.strip() else injected_prompt
            self.emit(
                'dm_chunk',
                dm_chunk_payload(
                    chunk=injected_chunk,
                    session_id=turn.session_id,
                    turn_id=turn.turn_id,
                    requires_roll=turn.requires_roll,
                    rules_hint=rules_hint_payload,
                    context_version=CONTEXT_VERSION,
                ),
                room=str(turn.session_id),
            )
            self.socketio.sleep(0)
            dm_response_text += injected_chunk
            telemetry_metric('socket.roll_prompt_injected_total', 1)

        response_emit_started = time.perf_counter()
        self.emit(
            'dm_response_end',
            dm_response_end_payload(
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                requires_roll=turn.requires_roll,
                rules_hint=rules_hint_payload,
                context_version=CONTEXT_VERSION,
                ok=stream_error is None,
                error=stream_error[:500] if stream_error else None,
            ),
            room=str(turn.session_id),
        )
        self._record_phase_timing(
            'dm_response_emit',
            response_emit_started,
            campaign_id=campaign.campaign_id,
            session_id=turn.session_id,
        )
        self._emit_turn_status(turn.session_id, turn.turn_id, 'response_complete', {'ok': stream_error is None})
        # Yield so the dm_response_end event is flushed to clients immediately,
        # before the heavy post-turn processing (DB writes, canon extraction,
        # session projection) that can take 30-120+ seconds.
        self.socketio.sleep(0)
        return dm_response_text, stream_error

    def _background_canon_job(self, app, job_id: int):
        with app.app_context():
            process_canon_job(
                job_id,
                emit_turn_status=self._emit_turn_status,
                emit_segment_triggered=lambda session_id, payload: self.socketio.emit(
                    'segment_triggered',
                    payload,
                    room=str(session_id),
                ),
                record_phase_timing=self._record_phase_timing,
            )

    def _persist_turn_outcome(
        self,
        *,
        turn: DmTurn,
        campaign: Campaign,
        command: TurnCommand,
        player_label: str,
        rules_hint_payload: dict,
        dm_response_text: str,
        stream_error: str | None,
        triggered_segments: list[dict],
        start_time: float,
    ) -> list[dict]:
        post_turn_segments: list[dict] = []
        try:
            db_save_started = time.perf_counter()
            dm_response_text = strip_reasoning_blocks(dm_response_text).strip()
            turn_obj = db.session.get(DmTurn, turn.turn_id)
            if turn_obj:
                turn_obj.completed_at = utc_now()
                turn_obj.latency_ms = int((time.perf_counter() - start_time) * 1000)
                turn_obj.llm_provider = current_app.config.get('AIDM_LLM_PROVIDER')
                turn_obj.llm_model = current_app.config.get('AIDM_LLM_MODEL')
                set_logging_context(turn_id=turn.turn_id)

                if dm_response_text:
                    turn_obj.dm_output = dm_response_text
                    turn_obj.status = 'completed'
                else:
                    turn_obj.status = 'failed' if stream_error else 'completed'
                    metadata_payload = safe_json_loads(turn_obj.metadata_json, {})
                    if stream_error:
                        metadata_payload['error'] = stream_error
                    turn_obj.metadata_json = safe_json_dumps(metadata_payload, {})

            if dm_response_text:
                record_turn_event(
                    session_id=turn.session_id,
                    campaign_id=campaign.campaign_id,
                    turn_id=turn.turn_id,
                    player_id=turn.player_id,
                    event_type=DM_RESPONSE_EVENT,
                    payload={
                        'message': dm_response_text,
                        'metadata': {
                            'turn_id': turn.turn_id,
                            'requires_roll': turn.requires_roll,
                            'rule_type': turn.rule_type,
                            'confidence': turn.confidence,
                            'outcome_status': 'deferred' if turn.outcome_status == 'deferred' else 'resolved',
                            'action_intent': command.action_intent,
                            'client_message_id': command.client_message_id,
                        },
                    },
                )

            db.session.commit()
            self._record_phase_timing(
                'db_save',
                db_save_started,
                campaign_id=campaign.campaign_id,
                session_id=turn.session_id,
            )
            self._emit_turn_status(turn.session_id, turn.turn_id, 'saved', {'stage': 'dm_response'})

            if turn_obj and (dm_response_text or triggered_segments):
                canon_job = enqueue_canon_job(
                    turn=turn_obj,
                    campaign=campaign,
                    speaking_player_name=player_label,
                    triggered_segments=triggered_segments,
                )
                db.session.commit()
                self._emit_turn_status(
                    turn.session_id,
                    turn.turn_id,
                    'canon_pending',
                    {'job_id': canon_job.job_id},
                )
                app = current_app._get_current_object()  # type: ignore[attr-defined]
                if current_app.config.get('TESTING') or current_app.config.get('AIDM_ENV') == 'test':
                    process_canon_job(
                        canon_job.job_id,
                        emit_turn_status=self._emit_turn_status,
                        emit_segment_triggered=lambda session_id, payload: self.socketio.emit(
                            'segment_triggered',
                            payload,
                            room=str(session_id),
                        ),
                        record_phase_timing=self._record_phase_timing,
                    )
                else:
                    self.socketio.start_background_task(
                        self._background_canon_job,
                        app,
                        canon_job.job_id,
                    )

            db.session.commit()
            self._emit_turn_status(turn.session_id, turn.turn_id, 'saved', {'stage': 'post_turn'})

            if dm_response_text:
                telemetry_metric('socket.send_message.success_total', 1)
                telemetry_timing(
                    'socket.turn_latency_ms',
                    float((time.perf_counter() - start_time) * 1000),
                    tags={'campaign_id': campaign.campaign_id, 'session_id': turn.session_id},
                )
            elif stream_error:
                telemetry_event(
                    'socket.turn_failed',
                    payload={'session_id': turn.session_id, 'turn_id': turn.turn_id, 'error': stream_error},
                    severity='error',
                )
            return post_turn_segments
        except Exception as exc:
            db.session.rollback()
            logger.error('Failed to persist DM response state: %s', str(exc))
            failed_turn = db.session.get(DmTurn, turn.turn_id)
            if failed_turn:
                metadata_payload = safe_json_loads(failed_turn.metadata_json, {})
                metadata_payload['post_turn_error'] = str(exc)
                metadata_payload['canon_status'] = 'failed'
                failed_turn.metadata_json = safe_json_dumps(metadata_payload, {})
                if failed_turn.dm_output:
                    failed_turn.status = 'completed'
                db.session.commit()
            self._emit_turn_status(turn.session_id, turn.turn_id, 'failed', {'stage': 'post_turn', 'error': str(exc)})
            self.socketio.emit(
                'error',
                socket_error(
                    'turn_persist_failed',
                    'The DM response was generated but could not be saved. Please retry; continuity may be affected.',
                    {'session_id': turn.session_id, 'turn_id': turn.turn_id},
                ),
                room=str(turn.session_id),
            )
            telemetry_event(
                'socket.dm_persist_failed',
                payload={'session_id': turn.session_id, 'turn_id': turn.turn_id, 'error': str(exc)},
                severity='error',
            )
            return []
