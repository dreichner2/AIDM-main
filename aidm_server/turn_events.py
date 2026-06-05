from __future__ import annotations

from typing import Any

from aidm_server.database import db
from aidm_server.models import PlayerAction, SessionLogEntry, TurnEvent, safe_json_dumps


PLAYER_MESSAGE_EVENT = 'player_message'
ROLL_RESOLVED_EVENT = 'roll_resolved'
DM_RESPONSE_EVENT = 'dm_response'
SEGMENT_TRIGGERED_EVENT = 'segment_triggered'
CANON_APPLIED_EVENT = 'canon_applied'


def record_turn_event(
    *,
    session_id: int,
    campaign_id: int,
    event_type: str,
    payload: dict[str, Any],
    turn_id: int | None = None,
    player_id: int | None = None,
    project_legacy: bool = True,
) -> TurnEvent:
    event = TurnEvent(
        session_id=session_id,
        campaign_id=campaign_id,
        turn_id=turn_id,
        player_id=player_id,
        event_type=event_type,
        payload_json=safe_json_dumps(payload, {}),
    )
    db.session.add(event)
    db.session.flush()

    if project_legacy:
        _project_turn_event(event, payload)
    return event


def _project_turn_event(event: TurnEvent, payload: dict[str, Any]):
    if event.event_type == PLAYER_MESSAGE_EVENT:
        message = str(payload.get('message') or '').strip()
        speaker = str(payload.get('speaker') or '').strip()
        if not message:
            return
        if event.player_id is not None:
            db.session.add(
                PlayerAction(
                    player_id=event.player_id,
                    session_id=event.session_id,
                    action_text=message,
                )
            )
        db.session.add(
            SessionLogEntry(
                session_id=event.session_id,
                message=f'{speaker}: {message}' if speaker else message,
                entry_type='player',
                metadata_json=safe_json_dumps(payload.get('metadata', {}), {}),
            )
        )
        return

    if event.event_type == ROLL_RESOLVED_EVENT:
        pending_turn_id = payload.get('pending_turn_id')
        roll_value = payload.get('roll_value')
        db.session.add(
            SessionLogEntry(
                session_id=event.session_id,
                message=f'**Check Resolved**: turn {pending_turn_id} resolved with roll {roll_value}.',
                entry_type='dm',
                metadata_json=safe_json_dumps(payload.get('metadata', {}), {}),
            )
        )
        return

    if event.event_type == DM_RESPONSE_EVENT:
        message = str(payload.get('message') or '').strip()
        if not message:
            return
        db.session.add(
            SessionLogEntry(
                session_id=event.session_id,
                message=f'DM: {message}',
                entry_type='dm',
                metadata_json=safe_json_dumps(payload.get('metadata', {}), {}),
            )
        )
        return

    if event.event_type == SEGMENT_TRIGGERED_EVENT:
        title = str(payload.get('title') or '').strip()
        if not title:
            return
        db.session.add(
            SessionLogEntry(
                session_id=event.session_id,
                message=f'**Segment Triggered**: {title}',
                entry_type='dm',
                metadata_json=safe_json_dumps(payload.get('metadata', {}), {}),
            )
        )
