from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

from flask import current_app

from aidm_server.database import db
from aidm_server.emergent_memory import (
    append_session_memory,
    apply_canon_patch,
    extract_canon_patch,
    refresh_session_projection,
    validate_canon_patch,
)
from aidm_server.errors import socket_error
from aidm_server.llm import CONTEXT_VERSION, build_dm_context
from aidm_server.logging_context import set_logging_context
from aidm_server.models import Campaign, CampaignSegment, DmTurn, Player, Session, safe_json_loads
from aidm_server.rules import RuleHint, classify_player_action
from aidm_server.segment_triggers import evaluate_segment_trigger, parse_trigger_spec
from aidm_server.telemetry import telemetry_event, telemetry_metric, telemetry_timing
from aidm_server.text_sanitization import ReasoningBlockFilter, strip_reasoning_blocks
from aidm_server.time_utils import utc_now
from aidm_server.turn_coordinator import session_turn_coordinator
from aidm_server.turn_events import (
    CANON_APPLIED_EVENT,
    DM_RESPONSE_EVENT,
    PLAYER_MESSAGE_EVENT,
    ROLL_RESOLVED_EVENT,
    SEGMENT_TRIGGERED_EVENT,
    record_turn_event,
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


class TurnEngine:
    def __init__(
        self,
        *,
        socketio,
        emit_fn: Callable,
        stream_fn: Callable,
        latest_pending_turn_fn: Callable[[int, int | None], DmTurn | None],
        dc_hint_from_turn_fn: Callable[[DmTurn | None], str | None],
        apply_pending_resolution_hint_fn: Callable[[int, int, RuleHint], tuple[DmTurn | None, int | None]],
        build_roll_prompt_fn: Callable[[RuleHint, int | None], str],
        response_mentions_roll_request_fn: Callable[[str], bool],
    ):
        self.socketio = socketio
        self.emit = emit_fn
        self.stream_fn = stream_fn
        self.latest_pending_turn = latest_pending_turn_fn
        self.dc_hint_from_turn = dc_hint_from_turn_fn
        self.apply_pending_resolution_hint = apply_pending_resolution_hint_fn
        self.build_roll_prompt = build_roll_prompt_fn
        self.response_mentions_roll_request = response_mentions_roll_request_fn

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

        if player.campaign_id != command.campaign_id:
            self.emit('error', socket_error('campaign_mismatch', 'Player not part of this campaign'))
            telemetry_event(
                'socket.send_message.campaign_mismatch',
                payload={'sid': command.sid, 'player_id': command.player_id, 'campaign_id': command.campaign_id},
                severity='warning',
            )
            return

        player_label = player.character_name
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

        pending_turn_before = self.latest_pending_turn(command.session_id, command.player_id)
        if pending_turn_before and rule_hint.roll_value is None:
            pending_rule_type = pending_turn_before.rule_type or 'check'
            pending_dc_hint = self.dc_hint_from_turn(pending_turn_before)
            roll_required_payload = {
                'session_id': command.session_id,
                'pending_turn_id': pending_turn_before.turn_id,
                'rule_type': pending_rule_type,
                'dc_hint': pending_dc_hint,
                'prompt': self.build_roll_prompt(
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
            }
            self.emit('roll_required', roll_required_payload)
            self.emit(
                'error',
                socket_error(
                    'roll_required',
                    'Resolve the pending check before taking a new action.',
                    roll_required_payload,
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

        if rule_hint.roll_value is not None and not pending_turn_before:
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
            rules_hint=json.dumps(rules_hint_payload),
            context_version=CONTEXT_VERSION,
            status='processing',
            metadata_json=json.dumps({'speaker': player_label, 'resolved_turn_id': resolved_turn_id}),
        )

        start_time = time.perf_counter()
        if not self._persist_incoming_turn(turn, player_label, command, rule_hint, pending_turn_to_resolve, resolved_turn_id):
            return

        self.emit(
            'new_message',
            {
                'message': command.user_input,
                'speaker': player_label,
                'turn_id': turn.turn_id,
                'requires_roll': rule_hint.requires_roll,
                'rules_hint': rules_hint_payload,
                'context_version': CONTEXT_VERSION,
            },
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
            rules_hint_payload=rules_hint_payload,
            resolved_turn_id=resolved_turn_id,
        )

        # Run the heavy post-turn work (DB writes, canon extraction LLM call,
        # session projection, segment evaluation) in a background thread so the
        # socket handler returns immediately.  This lets the long-polling
        # transport deliver dm_response_end to the client within seconds
        # instead of blocking for 30-120+ s of post-processing.
        app = current_app._get_current_object()  # type: ignore[attr-defined]
        post_turn_kwargs = {
            'turn': turn,
            'campaign': campaign,
            'command': command,
            'player_label': player_label,
            'rules_hint_payload': rules_hint_payload,
            'dm_response_text': dm_response_text,
            'stream_error': stream_error,
            'triggered_segments': triggered_segments,
            'start_time': start_time,
        }
        if current_app.config.get('TESTING') or current_app.config.get('AIDM_ENV') == 'test':
            self._background_post_turn(app, **post_turn_kwargs)
        else:
            self.socketio.start_background_task(
                self._background_post_turn,
                app,
                **post_turn_kwargs,
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

            self.socketio.emit('session_log_update', {'session_id': command.session_id, 'turn_id': turn.turn_id}, room=str(command.session_id))

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
                pending_turn_to_resolve.metadata_json = json.dumps(pending_metadata)
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

    @staticmethod
    def _segment_thread_patch(triggered_segments: list[dict]) -> dict:
        return {
            'entities': [],
            'facts': [],
            'threads': [
                {
                    'title': str(segment_payload.get('title') or '').strip(),
                    'summary': f'Authored story thread activated: {str(segment_payload.get("title") or "").strip()}.',
                    'status': 'open',
                    'priority': 2,
                    'source': 'segment',
                    'metadata': {
                        'segment_id': segment_payload.get('segment_id'),
                        'reason': segment_payload.get('reason'),
                    },
                }
                for segment_payload in triggered_segments
                if str(segment_payload.get('title') or '').strip()
            ],
            'inventory_changes': [],
            'projection': {},
        }

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

                    payload = {
                        'segment_id': seg.segment_id,
                        'title': seg.title,
                        'description': seg.description,
                        'reason': reason,
                        'trigger_spec': trigger_spec,
                    }
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
                    payload = {
                        'segment_id': seg.segment_id,
                        'title': seg.title,
                        'description': seg.description,
                        'reason': 'manual_override',
                        'trigger_spec': {'trigger_type': 'manual', 'raw': {'source': 'client_override'}},
                    }
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

    def _evaluate_state_segments_after_turn(self, turn: DmTurn, campaign: Campaign, command: TurnCommand) -> list[dict]:
        if not current_app.config.get('AIDM_SEGMENT_EVALUATOR_ENABLED', True):
            return []

        try:
            session_state_payload, campaign_state = self._segment_state_payload(command.session_id, campaign)
            segments_to_activate: list[tuple[CampaignSegment, dict]] = []
            untriggered_segments = CampaignSegment.query.filter_by(
                campaign_id=command.campaign_id,
                is_triggered=False,
            ).all()

            for seg in untriggered_segments:
                trigger_type = parse_trigger_spec(seg.trigger_condition).trigger_type
                if trigger_type != 'state':
                    continue

                matched, reason, trigger_spec = evaluate_segment_trigger(
                    trigger_condition=seg.trigger_condition,
                    player_message=command.user_input,
                    session_state=session_state_payload,
                    campaign_state=campaign_state,
                )
                if not matched:
                    continue

                payload = {
                    'segment_id': seg.segment_id,
                    'title': seg.title,
                    'description': seg.description,
                    'reason': reason,
                    'trigger_spec': trigger_spec,
                }
                segments_to_activate.append((seg, payload))

            return self._activate_segments(
                turn=turn,
                session_id=command.session_id,
                segments_to_activate=segments_to_activate,
            )
        except Exception as exc:
            logger.error('Post-turn state segment evaluation failed: %s', str(exc))
            telemetry_event(
                'socket.segment_state_evaluation_failed',
                payload={'session_id': command.session_id, 'campaign_id': command.campaign_id, 'error': str(exc)},
                severity='error',
            )
            return []

    def _narrate_turn(
        self,
        *,
        turn: DmTurn,
        campaign: Campaign,
        player_label: str,
        world_id: int,
        user_input: str,
        rules_hint_payload: dict,
        resolved_turn_id: int | None,
    ) -> tuple[str, str | None]:
        context = build_dm_context(world_id, campaign.campaign_id, turn.session_id, query_text=user_input)
        self.emit(
            'dm_response_start',
            {
                'session_id': turn.session_id,
                'turn_id': turn.turn_id,
                'requires_roll': turn.requires_roll,
                'rules_hint': rules_hint_payload,
                'context_version': CONTEXT_VERSION,
            },
            room=str(turn.session_id),
        )

        dm_response_text = ''
        stream_error = None
        reasoning_filter = ReasoningBlockFilter()
        try:
            for chunk in self.stream_fn(
                user_input,
                context,
                speaking_player={'character_name': player_label, 'player_id': str(turn.player_id)},
                rules_hint=rules_hint_payload,
            ):
                if not chunk:
                    continue
                chunk = reasoning_filter.filter(chunk)
                if not chunk:
                    continue
                self.emit(
                    'dm_chunk',
                    {
                        'chunk': chunk,
                        'session_id': turn.session_id,
                        'turn_id': turn.turn_id,
                        'requires_roll': turn.requires_roll,
                        'rules_hint': rules_hint_payload,
                        'context_version': CONTEXT_VERSION,
                    },
                    room=str(turn.session_id),
                )
                self.socketio.sleep(0)
                dm_response_text += chunk
            final_chunk = reasoning_filter.finish()
            if final_chunk:
                self.emit(
                    'dm_chunk',
                    {
                        'chunk': final_chunk,
                        'session_id': turn.session_id,
                        'turn_id': turn.turn_id,
                        'requires_roll': turn.requires_roll,
                        'rules_hint': rules_hint_payload,
                        'context_version': CONTEXT_VERSION,
                    },
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
                {
                    'chunk': injected_chunk,
                    'session_id': turn.session_id,
                    'turn_id': turn.turn_id,
                    'requires_roll': turn.requires_roll,
                    'rules_hint': rules_hint_payload,
                    'context_version': CONTEXT_VERSION,
                },
                room=str(turn.session_id),
            )
            self.socketio.sleep(0)
            dm_response_text += injected_chunk
            telemetry_metric('socket.roll_prompt_injected_total', 1)

        self.emit(
            'dm_response_end',
            {
                'session_id': turn.session_id,
                'turn_id': turn.turn_id,
                'requires_roll': turn.requires_roll,
                'rules_hint': rules_hint_payload,
                'context_version': CONTEXT_VERSION,
                'ok': stream_error is None,
            },
            room=str(turn.session_id),
        )
        # Yield so the dm_response_end event is flushed to clients immediately,
        # before the heavy post-turn processing (DB writes, canon extraction,
        # session projection) that can take 30-120+ seconds.
        self.socketio.sleep(0)
        return dm_response_text, stream_error

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
                    turn_obj.metadata_json = json.dumps(metadata_payload)

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
                        },
                    },
                )

            if turn_obj and (dm_response_text or triggered_segments):
                if dm_response_text:
                    append_session_memory(turn_obj)

                patch, extractor_model = extract_canon_patch(
                    turn=turn_obj,
                    campaign=campaign,
                    dm_output=dm_response_text,
                    speaking_player_name=player_label,
                    triggered_segments=triggered_segments,
                )
                validated_patch, rejections = validate_canon_patch(turn=turn_obj, campaign=campaign, patch=patch)
                if rejections:
                    telemetry_metric('memory.validation.rejections_total', len(rejections))
                    telemetry_event(
                        'memory.validation.rejections',
                        payload={'campaign_id': campaign.campaign_id, 'turn_id': turn.turn_id, 'rejections': rejections},
                        severity='warning',
                    )
                apply_canon_patch(
                    turn=turn_obj,
                    campaign=campaign,
                    patch=validated_patch,
                    extractor_model=extractor_model,
                    rejections=rejections,
                )
                record_turn_event(
                    session_id=turn.session_id,
                    campaign_id=campaign.campaign_id,
                    turn_id=turn.turn_id,
                    player_id=turn.player_id,
                    event_type=CANON_APPLIED_EVENT,
                    payload={
                        'extractor_model': extractor_model,
                        'rejection_count': len(rejections),
                        'thread_count': len(validated_patch.get('threads', [])),
                        'entity_count': len(validated_patch.get('entities', [])),
                        'fact_count': len(validated_patch.get('facts', [])),
                    },
                    project_legacy=False,
                )
                refresh_session_projection(session_id=turn.session_id, campaign=campaign, triggered_segments=triggered_segments)
                post_turn_segments = self._evaluate_state_segments_after_turn(turn_obj, campaign, command)
                if post_turn_segments:
                    segment_patch = self._segment_thread_patch(post_turn_segments)
                    validated_segment_patch, segment_rejections = validate_canon_patch(
                        turn=turn_obj,
                        campaign=campaign,
                        patch=segment_patch,
                    )
                    if segment_rejections:
                        telemetry_metric('memory.validation.rejections_total', len(segment_rejections))
                        telemetry_event(
                            'memory.validation.rejections',
                            payload={
                                'campaign_id': campaign.campaign_id,
                                'turn_id': turn.turn_id,
                                'rejections': segment_rejections,
                            },
                            severity='warning',
                        )
                    apply_canon_patch(
                        turn=turn_obj,
                        campaign=campaign,
                        patch=validated_segment_patch,
                        extractor_model='segment-state-v1',
                        rejections=segment_rejections,
                    )
                    refresh_session_projection(
                        session_id=turn.session_id,
                        campaign=campaign,
                        triggered_segments=post_turn_segments,
                    )

            db.session.commit()

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
