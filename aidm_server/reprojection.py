from __future__ import annotations

from aidm_server.database import db
from aidm_server.emergent_memory import refresh_session_projection
from aidm_server.models import PlayerAction, Session, SessionLogEntry, TurnEvent
from aidm_server.turn_events import project_turn_event


class ProjectionRepairError(RuntimeError):
    pass


def _state_payload(state) -> dict | None:
    if state is None:
        return None
    return {
        'current_location': state.current_location,
        'current_quest': state.current_quest,
        'updated_at': state.updated_at.isoformat() if state.updated_at else None,
    }


def _expunge_session_projection_rows(session_id: int):
    for obj in list(db.session.identity_map.values()):
        if isinstance(obj, (PlayerAction, SessionLogEntry)) and obj.session_id == session_id:
            db.session.expunge(obj)


def rebuild_legacy_event_projections(session_id: int) -> dict:
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        raise ProjectionRepairError(f'Session not found: {session_id}')

    deleted_logs = SessionLogEntry.query.filter_by(session_id=session_id).delete(synchronize_session=False)
    deleted_actions = PlayerAction.query.filter_by(session_id=session_id).delete(synchronize_session=False)
    _expunge_session_projection_rows(session_id)

    rebuilt = {'player_actions': 0, 'session_log_entries': 0}
    events = (
        TurnEvent.query.filter_by(session_id=session_id)
        .order_by(TurnEvent.created_at.asc(), TurnEvent.event_id.asc())
        .all()
    )
    for event in events:
        counts = project_turn_event(event, timestamp=event.created_at)
        rebuilt['player_actions'] += counts['player_actions']
        rebuilt['session_log_entries'] += counts['session_log_entries']

    db.session.flush()
    return {
        'session_id': session_id,
        'events_replayed': len(events),
        'deleted': {
            'player_actions': int(deleted_actions or 0),
            'session_log_entries': int(deleted_logs or 0),
        },
        'rebuilt': rebuilt,
    }


def repair_session_projections(session_id: int, *, commit: bool = False) -> dict:
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        raise ProjectionRepairError(f'Session not found: {session_id}')

    legacy_result = rebuild_legacy_event_projections(session_id)
    state = refresh_session_projection(session_id, session_obj.campaign)
    result = {
        'session_id': session_id,
        'legacy_projections': legacy_result,
        'session_state': _state_payload(state),
    }
    if commit:
        db.session.commit()
    return result


def repair_all_session_projections(*, commit: bool = False) -> list[dict]:
    session_ids = [row[0] for row in db.session.query(Session.session_id).order_by(Session.session_id.asc()).all()]
    results = [repair_session_projections(session_id, commit=False) for session_id in session_ids]
    if commit:
        db.session.commit()
    return results
