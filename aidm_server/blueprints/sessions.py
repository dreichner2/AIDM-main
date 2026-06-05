from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.llm import query_gpt
from aidm_server.models import (
    Campaign,
    DmCoherenceFeedback,
    DmTurn,
    PlayerAction,
    Session,
    SessionLogEntry,
    SessionState,
    StoryEntity,
    StoryFact,
    StoryThread,
    TurnEvent,
    TurnCanonUpdate,
    get_or_create_session_state,
    safe_json_loads,
)
from aidm_server.telemetry import telemetry_event, telemetry_metric
from aidm_server.time_utils import utc_now
from aidm_server.turn_coordinator import session_turn_coordinator
from aidm_server.validation import missing_fields, parse_json_body


logger = logging.getLogger(__name__)
sessions_bp = Blueprint('sessions', __name__)
RECAP_RECENT_ENTRY_LIMIT = 80
RECAP_SOURCE_CHAR_BUDGET = 12_000


def _state_snapshot_payload(raw_snapshot):
    return safe_json_loads(raw_snapshot, None)


def _state_snapshot_dict(raw_snapshot) -> dict:
    snapshot = safe_json_loads(raw_snapshot, {})
    return snapshot if isinstance(snapshot, dict) else {}


def _merge_state_snapshot(raw_snapshot, updates: dict) -> dict:
    snapshot = _state_snapshot_dict(raw_snapshot)
    snapshot.update(updates)
    return snapshot


def _isoformat(value):
    return value.isoformat() if value else None


def _latest_isoformat(*values):
    iso_values = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            iso_values.append(value)
        else:
            iso_values.append(value.isoformat())
    return max(iso_values) if iso_values else None


def _session_display_name(session_obj: Session, snapshot: dict) -> str:
    raw_name = snapshot.get('name') or snapshot.get('title')
    name = str(raw_name or '').strip()
    return name or f"Session {session_obj.session_id}"


def _session_summary_payload(session_obj: Session) -> dict:
    snapshot = _state_snapshot_dict(session_obj.state_snapshot)
    session_state = SessionState.query.filter_by(session_id=session_obj.session_id).first()
    latest_log_at = db.session.query(func.max(SessionLogEntry.timestamp)).filter_by(session_id=session_obj.session_id).scalar()
    latest_turn_created_at = db.session.query(func.max(DmTurn.created_at)).filter_by(session_id=session_obj.session_id).scalar()
    latest_turn_completed_at = db.session.query(func.max(DmTurn.completed_at)).filter_by(session_id=session_obj.session_id).scalar()
    turn_count = db.session.query(func.count(DmTurn.turn_id)).filter_by(session_id=session_obj.session_id).scalar() or 0
    snapshot_updated_at = snapshot.get('updated_at')

    latest_activity = _latest_isoformat(
        session_obj.created_at,
        snapshot_updated_at if isinstance(snapshot_updated_at, str) else None,
        session_state.updated_at if session_state else None,
        latest_log_at,
        latest_turn_created_at,
        latest_turn_completed_at,
    )
    latest_summary = ''
    if session_state and session_state.rolling_summary:
        latest_summary = session_state.rolling_summary
    elif isinstance(snapshot.get('recap'), str):
        latest_summary = snapshot['recap']
    elif isinstance(snapshot.get('summary'), str):
        latest_summary = snapshot['summary']

    return {
        'session_id': session_obj.session_id,
        'campaign_id': session_obj.campaign_id,
        'created_at': _isoformat(session_obj.created_at),
        'updated_at': latest_activity,
        'latest_activity_at': latest_activity,
        'display_name': _session_display_name(session_obj, snapshot),
        'turn_count': int(turn_count),
        'latest_summary': latest_summary,
        'is_archived': bool(snapshot.get('is_archived') or snapshot.get('archived')),
        'state_snapshot': _state_snapshot_payload(session_obj.state_snapshot),
    }


def _session_state_payload(session_obj: Session, session_state: SessionState | None) -> dict:
    if session_state is None:
        return {
            'session_id': session_obj.session_id,
            'campaign_id': session_obj.campaign_id,
            'current_location': session_obj.campaign.location,
            'current_quest': session_obj.campaign.current_quest,
            'rolling_summary': '',
            'active_segments': [],
            'memory_snippets': [],
            'updated_at': None,
        }

    return {
        'session_id': session_obj.session_id,
        'campaign_id': session_obj.campaign_id,
        'current_location': session_state.current_location,
        'current_quest': session_state.current_quest,
        'rolling_summary': session_state.rolling_summary,
        'active_segments': safe_json_loads(session_state.active_segments, []),
        'memory_snippets': safe_json_loads(session_state.memory_snippets, []),
        'updated_at': session_state.updated_at.isoformat() if session_state.updated_at else None,
    }


def _turn_event_payload(event: TurnEvent) -> dict:
    return {
        'event_id': event.event_id,
        'session_id': event.session_id,
        'campaign_id': event.campaign_id,
        'turn_id': event.turn_id,
        'player_id': event.player_id,
        'event_type': event.event_type,
        'payload': safe_json_loads(event.payload_json, {}),
        'created_at': event.created_at.isoformat() if event.created_at else None,
    }


def _bounded_session_recap_source(session_id: int, session_state: SessionState | None) -> str:
    entries = (
        SessionLogEntry.query.filter_by(session_id=session_id)
        .order_by(SessionLogEntry.timestamp.desc(), SessionLogEntry.id.desc())
        .limit(RECAP_RECENT_ENTRY_LIMIT)
        .all()
    )
    recent_log = "\n".join(entry.message for entry in reversed(entries))
    if len(recent_log) > RECAP_SOURCE_CHAR_BUDGET:
        recent_log = recent_log[-RECAP_SOURCE_CHAR_BUDGET:]

    parts = []
    rolling_summary = (session_state.rolling_summary if session_state else '') or ''
    if rolling_summary:
        parts.append(f'Existing rolling summary:\n{rolling_summary[-4000:]}')
    if recent_log:
        parts.append(
            f'Recent session log (last {len(entries)} entries, bounded to {RECAP_SOURCE_CHAR_BUDGET} chars):\n'
            f'{recent_log}'
        )
    return "\n\n".join(parts) or 'No session log entries have been recorded for this session.'


@sessions_bp.route('/start', methods=['POST'])
def start_new_session():
    telemetry_metric('sessions.start.requests_total', 1)
    payload = parse_json_body(request)
    required = missing_fields(payload, ['campaign_id'])
    if required:
        telemetry_event('sessions.start.validation_error', payload={'missing_fields': required}, severity='warning')
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    campaign = db.session.get(Campaign, payload['campaign_id'])
    if not campaign:
        telemetry_event('sessions.start.campaign_not_found', payload={'campaign_id': payload['campaign_id']}, severity='warning')
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    try:
        new_session = Session(campaign_id=campaign.campaign_id)
        db.session.add(new_session)
        db.session.flush()

        get_or_create_session_state(new_session.session_id, campaign)
        db.session.add(
            SessionLogEntry(
                session_id=new_session.session_id,
                entry_type='system',
                message='**Welcome to the table. Choose your opening move when you are ready.**',
                metadata_json=json.dumps({'kind': 'session_welcome'}),
            )
        )
        db.session.commit()
        telemetry_metric('sessions.start.success_total', 1)
        return jsonify({'session_id': new_session.session_id}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to start session: %s', str(exc))
        telemetry_event('sessions.start.failed', payload={'error': str(exc)}, severity='error')
        return error_response('session_start_failed', 'Failed to start session.', 400)


@sessions_bp.route('/<int:session_id>/end', methods=['POST'])
def end_game_session(session_id):
    telemetry_metric('sessions.end.requests_total', 1)
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        telemetry_event('sessions.end.session_not_found', payload={'session_id': session_id}, severity='warning')
        return error_response('session_not_found', 'Session not found.', 404)

    session_state = get_or_create_session_state(session_id, session_obj.campaign)
    recap_source = _bounded_session_recap_source(session_id, session_state)
    recap_prompt = (
        'Please provide a concise summary of this D&D session, highlighting key events, '
        'important decisions, and significant character developments. Use the existing '
        'rolling summary for continuity and the bounded recent log for latest events:\n\n'
        f'{recap_source}'
    )

    recap = query_gpt(prompt=recap_prompt, system_message='You are a D&D session summarizer.')

    try:
        snapshot = {
            'recap': recap,
            'ended_at': utc_now().isoformat(),
        }
        session_obj.state_snapshot = json.dumps(snapshot)

        session_state.rolling_summary = recap
        session_state.current_location = (session_state.current_location or session_obj.campaign.location)
        session_state.current_quest = (session_state.current_quest or session_obj.campaign.current_quest)
        session_state.updated_at = utc_now()

        db.session.commit()
        telemetry_metric('sessions.end.success_total', 1)
        return jsonify({'recap': recap})
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to end session: %s', str(exc))
        telemetry_event(
            'sessions.end.failed',
            payload={'session_id': session_id, 'error': str(exc)},
            severity='error',
        )
        return error_response('session_end_failed', 'Failed to end session.', 400)


@sessions_bp.route('/campaigns/<int:campaign_id>/sessions', methods=['GET'])
def list_campaign_sessions(campaign_id):
    telemetry_metric('sessions.list.requests_total', 1)
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        telemetry_event('sessions.list.campaign_not_found', payload={'campaign_id': campaign_id}, severity='warning')
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    sessions = Session.query.filter_by(campaign_id=campaign_id).order_by(Session.created_at.desc()).all()
    session_payloads = [_session_summary_payload(s) for s in sessions]
    session_payloads.sort(key=lambda item: item.get('latest_activity_at') or '', reverse=True)
    return jsonify(session_payloads)


@sessions_bp.route('/<int:session_id>', methods=['PATCH'])
def update_session(session_id):
    telemetry_metric('sessions.update.requests_total', 1)
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        telemetry_event('sessions.update.session_not_found', payload={'session_id': session_id}, severity='warning')
        return error_response('session_not_found', 'Session not found.', 404)

    raw_name = payload.get('name', payload.get('title'))
    name = str(raw_name or '').strip()
    if not name:
        return error_response('validation_error', 'Session name is required.', 400)
    if len(name) > 80:
        return error_response('validation_error', 'Session name must be 80 characters or fewer.', 400)

    try:
        snapshot = _merge_state_snapshot(
            session_obj.state_snapshot,
            {
                'name': name,
                'updated_at': utc_now().isoformat(),
            },
        )
        session_obj.state_snapshot = json.dumps(snapshot)
        db.session.commit()
        telemetry_metric('sessions.update.success_total', 1)
        return jsonify(_session_summary_payload(session_obj))
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to update session: %s', str(exc))
        telemetry_event('sessions.update.failed', payload={'session_id': session_id, 'error': str(exc)}, severity='error')
        return error_response('session_update_failed', 'Failed to update session.', 400)


@sessions_bp.route('/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    telemetry_metric('sessions.delete.requests_total', 1)
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        telemetry_event('sessions.delete.session_not_found', payload={'session_id': session_id}, severity='warning')
        return error_response('session_not_found', 'Session not found.', 404)

    try:
        session_turn_ids = select(DmTurn.turn_id).where(DmTurn.session_id == session_id)
        TurnCanonUpdate.query.filter(TurnCanonUpdate.turn_id.in_(session_turn_ids)).delete(synchronize_session=False)
        StoryFact.query.filter(StoryFact.source_turn_id.in_(session_turn_ids)).update(
            {StoryFact.source_turn_id: None},
            synchronize_session=False,
        )
        StoryThread.query.filter(StoryThread.origin_turn_id.in_(session_turn_ids)).update(
            {StoryThread.origin_turn_id: None},
            synchronize_session=False,
        )
        StoryThread.query.filter(StoryThread.last_touched_turn_id.in_(session_turn_ids)).update(
            {StoryThread.last_touched_turn_id: None},
            synchronize_session=False,
        )
        StoryThread.query.filter(StoryThread.resolved_turn_id.in_(session_turn_ids)).update(
            {StoryThread.resolved_turn_id: None},
            synchronize_session=False,
        )
        StoryEntity.query.filter(StoryEntity.first_seen_turn_id.in_(session_turn_ids)).update(
            {StoryEntity.first_seen_turn_id: None},
            synchronize_session=False,
        )
        StoryEntity.query.filter(StoryEntity.last_seen_turn_id.in_(session_turn_ids)).update(
            {StoryEntity.last_seen_turn_id: None},
            synchronize_session=False,
        )

        StoryEntity.query.filter_by(session_id=session_id).update({StoryEntity.session_id: None}, synchronize_session=False)
        DmCoherenceFeedback.query.filter_by(session_id=session_id).delete(synchronize_session=False)
        PlayerAction.query.filter_by(session_id=session_id).delete(synchronize_session=False)
        SessionState.query.filter_by(session_id=session_id).delete(synchronize_session=False)
        db.session.delete(session_obj)
        db.session.commit()
        session_turn_coordinator.discard_session(session_id)
        telemetry_metric('sessions.delete.success_total', 1)
        return jsonify({'deleted': True, 'session_id': session_id})
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to delete session: %s', str(exc))
        telemetry_event('sessions.delete.failed', payload={'session_id': session_id, 'error': str(exc)}, severity='error')
        return error_response('session_delete_failed', 'Failed to delete session.', 400)


@sessions_bp.route('/<int:session_id>/log', methods=['GET'])
def get_session_log(session_id):
    telemetry_metric('sessions.log.requests_total', 1)
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        telemetry_event('sessions.log.session_not_found', payload={'session_id': session_id}, severity='warning')
        return error_response('session_not_found', 'Session not found.', 404)

    limit = request.args.get('limit', default=200, type=int)
    limit = max(1, min(limit, 500))

    entries = (
        SessionLogEntry.query.filter_by(session_id=session_id)
        .order_by(SessionLogEntry.timestamp.desc(), SessionLogEntry.id.desc())
        .limit(limit)
        .all()
    )
    entries = list(reversed(entries))
    return jsonify(
        {
            'session_id': session_id,
            'entries': [
                {
                    'id': entry.id,
                    'message': entry.message,
                    'entry_type': entry.entry_type,
                    'metadata': safe_json_loads(entry.metadata_json, {}),
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                }
                for entry in entries
            ],
        }
    )


@sessions_bp.route('/<int:session_id>/events', methods=['GET'])
def get_session_events(session_id):
    telemetry_metric('sessions.events.requests_total', 1)
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        telemetry_event('sessions.events.session_not_found', payload={'session_id': session_id}, severity='warning')
        return error_response('session_not_found', 'Session not found.', 404)

    limit = request.args.get('limit', default=500, type=int)
    limit = max(1, min(limit, 1000))

    events = (
        TurnEvent.query.filter_by(session_id=session_id)
        .order_by(TurnEvent.created_at.desc(), TurnEvent.event_id.desc())
        .limit(limit)
        .all()
    )
    events = list(reversed(events))
    return jsonify(
        {
            'session_id': session_id,
            'events': [_turn_event_payload(event) for event in events],
        }
    )


@sessions_bp.route('/<int:session_id>/state', methods=['GET'])
def get_session_state(session_id):
    telemetry_metric('sessions.state.requests_total', 1)
    session_obj = db.session.get(Session, session_id)
    if not session_obj:
        telemetry_event('sessions.state.session_not_found', payload={'session_id': session_id}, severity='warning')
        return error_response('session_not_found', 'Session not found.', 404)

    session_state = SessionState.query.filter_by(session_id=session_id).first()
    return jsonify(_session_state_payload(session_obj, session_state))
