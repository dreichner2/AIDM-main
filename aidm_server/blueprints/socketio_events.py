from __future__ import annotations

import logging
import re

from flask import current_app, request
from flask_socketio import emit, join_room, leave_room

from aidm_server.auth import extract_socket_token, is_token_authorized
from aidm_server.database import db
from aidm_server.errors import socket_error
from aidm_server.llm import CONTEXT_VERSION, query_dm_function_stream
from aidm_server.logging_context import clear_logging_context, new_correlation_id, set_logging_context
from aidm_server.models import (
    DmTurn,
    Player,
    Session,
    safe_json_loads,
)
from aidm_server.rate_limiter import FixedWindowRateLimiter
from aidm_server.rules import RuleHint
from aidm_server.telemetry import telemetry_event, telemetry_metric
from aidm_server.turn_engine import TurnCommand, TurnEngine
from aidm_server.validation import coerce_int


logger = logging.getLogger(__name__)

# {session_id: {player_id: {id, character_name, name, _sids}}}
active_players: dict[int, dict[int, dict]] = {}
# {sid: {session_id, player_id, authorized, correlation_id}}
socketio_connections: dict[str, dict] = {}

_socket_limiter: FixedWindowRateLimiter | None = None


def _coerce_int_list(value) -> list[int]:
    if not isinstance(value, list):
        return []
    parsed: list[int] = []
    for item in value:
        parsed_item = coerce_int(item)
        if parsed_item is not None:
            parsed.append(parsed_item)
    return parsed


def _latest_pending_turn(session_id: int, player_id: int | None = None) -> DmTurn | None:
    query = DmTurn.query.filter_by(session_id=session_id, outcome_status='deferred')
    if player_id is not None:
        query = query.filter_by(player_id=player_id)
    return query.order_by(DmTurn.turn_id.desc()).first()


def _dc_hint_from_turn(turn: DmTurn | None) -> str | None:
    if not turn:
        return None
    rules_hint = safe_json_loads(turn.rules_hint, {})
    if not isinstance(rules_hint, dict):
        return None
    dc_hint = rules_hint.get('dc_hint')
    if not dc_hint:
        return None
    return str(dc_hint)


def _apply_pending_resolution_hint(session_id: int, player_id: int, rule_hint: RuleHint) -> tuple[DmTurn | None, int | None]:
    if rule_hint.roll_value is None:
        return None, None

    pending_turn = _latest_pending_turn(session_id, player_id)
    if not pending_turn:
        return None, None

    pending_rule_type = pending_turn.rule_type or 'check'
    pending_dc_hint = _dc_hint_from_turn(pending_turn)

    rule_hint.requires_roll = True
    rule_hint.outcome_deferred = False
    if rule_hint.roll_type in (None, 'check'):
        rule_hint.roll_type = pending_rule_type
    if not rule_hint.dc_hint and pending_dc_hint:
        rule_hint.dc_hint = pending_dc_hint
    rule_hint.reason = f'Resolved pending {pending_rule_type} from turn {pending_turn.turn_id}'
    pending_confidence = pending_turn.confidence if pending_turn.confidence is not None else 0.8
    rule_hint.confidence = max(rule_hint.confidence, pending_confidence)

    return pending_turn, pending_turn.turn_id


_ROLL_TYPE_LABELS = {
    'attack': 'an Attack roll',
    'stealth': 'a Dexterity (Stealth) check',
    'social': 'a Charisma (Persuasion/Deception) check',
    'lore': 'an Intelligence (Investigation/Arcana) check',
    'athletics': 'a Strength (Athletics) check',
    'thieves_tools': "a Dexterity (Thieves' Tools) check",
    'mobility': 'a Dexterity (Acrobatics) or Strength (Athletics) check',
    'check': 'an appropriate ability check',
}


_ROLL_REQUEST_PATTERNS = [
    re.compile(r'\bplease\s+roll\b', re.IGNORECASE),
    re.compile(r'\broll\s+(?:a\s+)?d20\b', re.IGNORECASE),
    re.compile(r'\bmake\s+(?:an?\s+)?[a-z][a-z \'-]{0,40}\s+check\b', re.IGNORECASE),
    re.compile(r'\bwhat\s+did\s+you\s+roll\b', re.IGNORECASE),
    re.compile(r'\broll\s+for\b', re.IGNORECASE),
]


def _build_roll_prompt(rule_hint: RuleHint, pending_turn_id: int | None = None) -> str:
    roll_label = _ROLL_TYPE_LABELS.get(rule_hint.roll_type or 'check', 'an appropriate ability check')
    dc_hint = f" (DC {rule_hint.dc_hint})" if rule_hint.dc_hint else ''
    pending_prefix = f'Resolve pending turn {pending_turn_id}: ' if pending_turn_id else ''
    return (
        f'{pending_prefix}Please roll {roll_label}{dc_hint} and send the result '
        '(example: "I roll a d20: 14").'
    )


def _response_mentions_roll_request(text: str) -> bool:
    candidate = text or ''
    return any(pattern.search(candidate) for pattern in _ROLL_REQUEST_PATTERNS)


def _set_socket_context(event_name: str, data: dict | None = None, turn_id: int | None = None):
    sid = getattr(request, 'sid', 'unknown')
    connection = socketio_connections.get(sid, {})
    correlation_id = (
        (data or {}).get('correlation_id')
        or connection.get('correlation_id')
        or new_correlation_id(prefix=f'socket-{event_name}')
    )
    session_id = (data or {}).get('session_id') or connection.get('session_id')

    set_logging_context(correlation_id=correlation_id, session_id=session_id, turn_id=turn_id)
    if sid:
        connection['correlation_id'] = correlation_id
        socketio_connections[sid] = connection


def _socket_rate_limiter() -> FixedWindowRateLimiter:
    global _socket_limiter
    if _socket_limiter is None:
        _socket_limiter = FixedWindowRateLimiter(
            limit=current_app.config.get('AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES', 40),
            window_seconds=current_app.config.get('AIDM_RATE_LIMIT_WINDOW_SECONDS', 30),
        )
    return _socket_limiter


def _socket_auth_required() -> bool:
    try:
        return bool(current_app.config.get('AIDM_AUTH_REQUIRED', False))
    except Exception:
        return False


def _is_socket_authorized(auth_payload: dict | None = None, data_payload: dict | None = None) -> bool:
    if not _socket_auth_required():
        return True
    sid = getattr(request, 'sid', None)
    existing = socketio_connections.get(sid) if sid else None
    if existing and existing.get('authorized'):
        return True
    token = extract_socket_token(auth_payload=auth_payload, data_payload=data_payload)
    return is_token_authorized(token)


def _active_player_payloads(session_id: int) -> list[dict]:
    return [
        {key: value for key, value in player_data.items() if not key.startswith('_')}
        for player_data in active_players.get(session_id, {}).values()
    ]


def _track_active_player(session_id: int, player_data: dict, sid: str) -> bool:
    session_players = active_players.setdefault(session_id, {})
    player_id = player_data['id']
    existing = session_players.get(player_id)
    if existing:
        existing.update({key: value for key, value in player_data.items() if not key.startswith('_')})
        sids = existing.setdefault('_sids', set())
        sids.add(sid)
        return False

    session_players[player_id] = {
        **player_data,
        '_sids': {sid},
    }
    return True


def _release_active_player(session_id: int, player_id: int, sid: str) -> bool:
    session_players = active_players.get(session_id)
    if not session_players:
        return False

    existing = session_players.get(player_id)
    if not existing:
        return False

    sids = existing.get('_sids')
    if not isinstance(sids, set):
        sids = set()
    sids.discard(sid)
    if sids:
        existing['_sids'] = sids
        return False

    del session_players[player_id]
    if not session_players:
        del active_players[session_id]
    return True


def register_socketio_events(socketio):
    def _clear_connection_binding(sid: str, *, leave_bound_room: bool):
        connection_record = socketio_connections.get(sid)
        if not connection_record:
            return

        session_id = coerce_int(connection_record.get('session_id'))
        player_id = coerce_int(connection_record.get('player_id'))
        if leave_bound_room and session_id:
            leave_room(str(session_id))
        if session_id and player_id and _release_active_player(session_id, player_id, sid):
            emit('player_left', {'id': player_id}, room=str(session_id))
            emit('active_players', _active_player_payloads(session_id), room=str(session_id))
        connection_record['session_id'] = None
        connection_record['player_id'] = None

    @socketio.on('connect')
    def handle_connect(auth=None):
        _set_socket_context('connect', auth if isinstance(auth, dict) else None)
        try:
            try:
                sid = getattr(request, 'sid', None)
                remote_addr = getattr(request, 'remote_addr', None)
                authorized = _is_socket_authorized(auth_payload=auth)

                if not authorized:
                    logger.warning('Socket auth rejected sid=%s', sid)
                    telemetry_event(
                        'socket.connect.unauthorized',
                        payload={'sid': sid, 'remote_addr': remote_addr},
                        severity='warning',
                    )
                    return False

                if sid:
                    socketio_connections[sid] = {
                        'authorized': True,
                        'session_id': None,
                        'player_id': None,
                        'correlation_id': socketio_connections.get(sid, {}).get('correlation_id'),
                    }
                telemetry_metric('socket.connect.success_total', 1)
                return None
            except Exception as exc:
                logger.exception('Socket connect handler failed: %s', str(exc))
                telemetry_event(
                    'socket.connect.error',
                    payload={'error': str(exc)},
                    severity='error',
                )
                return False
        finally:
            clear_logging_context()

    @socketio.on('join_session')
    def handle_join_session(data):
        _set_socket_context('join_session', data if isinstance(data, dict) else None)
        try:
            if not isinstance(data, dict):
                emit('error', socket_error('validation_error', 'Expected object payload for join_session.'))
                telemetry_event('socket.join.validation_error', payload={'sid': request.sid}, severity='warning')
                return

            if not _is_socket_authorized(data_payload=data):
                emit('error', socket_error('unauthorized', 'Missing or invalid auth token.'))
                telemetry_event('socket.join.unauthorized', payload={'sid': request.sid}, severity='warning')
                return

            session_id = coerce_int(data.get('session_id'))
            player_id = coerce_int(data.get('player_id'))
            set_logging_context(session_id=session_id)

            if not session_id:
                emit('error', socket_error('validation_error', 'Session ID is required to join.'))
                telemetry_event('socket.join.validation_error', payload={'sid': request.sid}, severity='warning')
                return

            session_obj = db.session.get(Session, session_id)
            if not session_obj:
                emit('error', socket_error('session_not_found', 'Session not found.'))
                telemetry_event(
                    'socket.join.session_not_found',
                    payload={'sid': request.sid, 'session_id': session_id},
                    severity='warning',
                )
                return

            player_data = None
            if player_id:
                player = db.session.get(Player, player_id)
                if not player:
                    emit('error', socket_error('invalid_player', 'Invalid player ID.'))
                    telemetry_event(
                        'socket.join.invalid_player',
                        payload={'sid': request.sid, 'session_id': session_id, 'player_id': player_id},
                        severity='warning',
                    )
                    return
                if player.campaign_id != session_obj.campaign_id:
                    emit('error', socket_error('campaign_mismatch', 'Player not part of this session campaign.'))
                    telemetry_event(
                        'socket.join.campaign_mismatch',
                        payload={'sid': request.sid, 'session_id': session_id, 'player_id': player_id},
                        severity='warning',
                    )
                    return
                player_data = {
                    'id': player.player_id,
                    'character_name': player.character_name,
                    'name': player.name,
                }

            connection_record = socketio_connections.setdefault(request.sid, {'authorized': True})
            existing_session_id = coerce_int(connection_record.get('session_id'))
            existing_player_id = coerce_int(connection_record.get('player_id'))
            if existing_session_id != session_id or existing_player_id != player_id:
                _clear_connection_binding(request.sid, leave_bound_room=True)

            join_room(str(session_id))
            connection_record['session_id'] = session_id
            connection_record['player_id'] = player_id

            if session_id not in active_players:
                active_players[session_id] = {}

            if player_id:
                if player_data:
                    joined_fresh = _track_active_player(session_id, player_data, request.sid)
                    if joined_fresh:
                        emit('player_joined', player_data, room=str(session_id))
            emit('active_players', _active_player_payloads(session_id), room=str(session_id))
            emit(
                'new_message',
                {
                    'message': f'A new player joined session {session_id}!',
                    'context_version': CONTEXT_VERSION,
                },
                room=str(session_id),
            )
            telemetry_metric('socket.join.success_total', 1)
        finally:
            clear_logging_context()

    @socketio.on('leave_session')
    def handle_leave_session(data):
        _set_socket_context('leave_session', data if isinstance(data, dict) else None)
        try:
            if not isinstance(data, dict):
                emit('error', socket_error('validation_error', 'Expected object payload for leave_session.'))
                telemetry_event('socket.leave.validation_error', payload={'sid': request.sid}, severity='warning')
                return

            session_id = coerce_int(data.get('session_id'))
            player_id = coerce_int(data.get('player_id'))
            set_logging_context(session_id=session_id)

            if not session_id or not player_id:
                emit('error', socket_error('validation_error', 'session_id and player_id are required'))
                telemetry_event('socket.leave.validation_error', payload={'sid': request.sid}, severity='warning')
                return

            connection_record = socketio_connections.get(request.sid)
            bound_session_id = coerce_int(connection_record.get('session_id')) if connection_record else None
            bound_player_id = coerce_int(connection_record.get('player_id')) if connection_record else None
            if bound_session_id != session_id or bound_player_id != player_id:
                emit(
                    'error',
                    socket_error(
                        'player_identity_mismatch',
                        'This socket can only leave the session/player binding it joined with.',
                    ),
                )
                telemetry_event(
                    'socket.leave.player_identity_mismatch',
                    payload={
                        'sid': request.sid,
                        'session_id': session_id,
                        'player_id': player_id,
                        'bound_session_id': bound_session_id,
                        'bound_player_id': bound_player_id,
                    },
                    severity='warning',
                )
                return

            leave_room(str(session_id))

            removed_player = _release_active_player(session_id, player_id, request.sid)
            if removed_player:
                emit('player_left', {'id': player_id}, room=str(session_id))
                emit('active_players', _active_player_payloads(session_id), room=str(session_id))

            if connection_record is not None:
                connection_record['session_id'] = None
                connection_record['player_id'] = None
            telemetry_metric('socket.leave.success_total', 1)
        finally:
            clear_logging_context()

    @socketio.on('disconnect')
    def handle_disconnect():
        _set_socket_context('disconnect')
        try:
            connection_info = socketio_connections.pop(request.sid, None)
            if not connection_info:
                return

            session_id = connection_info.get('session_id')
            player_id = connection_info.get('player_id')
            set_logging_context(session_id=session_id)

            if session_id and player_id and _release_active_player(session_id, player_id, request.sid):
                emit('player_left', {'id': player_id}, room=str(session_id))
                emit('active_players', _active_player_payloads(session_id), room=str(session_id))
            telemetry_metric('socket.disconnect_total', 1)
        finally:
            clear_logging_context()

    @socketio.on('send_message')
    def handle_send_message(data):
        _set_socket_context('send_message', data if isinstance(data, dict) else None)
        try:
            telemetry_metric('socket.messages_total', 1)
            if not isinstance(data, dict):
                emit('error', socket_error('validation_error', 'Expected object payload for send_message.'))
                telemetry_event('socket.send_message.validation_error', payload={'sid': request.sid}, severity='warning')
                return

            if not _is_socket_authorized(data_payload=data):
                emit('error', socket_error('unauthorized', 'Missing or invalid auth token.'))
                telemetry_event('socket.send_message.unauthorized', payload={'sid': request.sid}, severity='warning')
                return

            required_fields = ['session_id', 'campaign_id', 'message', 'player_id']
            missing = [field for field in required_fields if data.get(field) in (None, '')]
            if missing:
                emit(
                    'error',
                    socket_error(
                        'validation_error',
                        'Missing required data.',
                        {'required_fields': required_fields, 'missing_fields': missing},
                    ),
                )
                telemetry_event(
                    'socket.send_message.validation_error',
                    payload={'sid': request.sid, 'missing_fields': missing},
                    severity='warning',
                )
                return

            session_id = coerce_int(data.get('session_id'))
            campaign_id = coerce_int(data.get('campaign_id'))
            world_id = coerce_int(data.get('world_id'), 0)
            player_id = coerce_int(data.get('player_id'))
            user_input = str(data.get('message') or '').strip()
            manual_segment_ids = set(_coerce_int_list(data.get('manual_trigger_segment_ids')))

            if not session_id or not campaign_id or not player_id or not user_input:
                emit('error', socket_error('validation_error', 'Invalid message payload types.'))
                telemetry_event('socket.send_message.validation_error', payload={'sid': request.sid}, severity='warning')
                return

            if manual_segment_ids:
                emit(
                    'error',
                    socket_error(
                        'manual_segment_override_disabled',
                        'Client-driven manual segment triggering is disabled.',
                    ),
                )
                telemetry_event(
                    'socket.send_message.manual_segment_override_disabled',
                    payload={'sid': request.sid, 'session_id': session_id, 'player_id': player_id},
                    severity='warning',
                )
                return

            set_logging_context(session_id=session_id)

            connection_record = socketio_connections.get(request.sid)
            bound_session_id = coerce_int(connection_record.get('session_id')) if connection_record else None
            bound_player_id = coerce_int(connection_record.get('player_id')) if connection_record else None
            if bound_session_id != session_id or bound_player_id != player_id:
                emit(
                    'error',
                    socket_error(
                        'player_identity_mismatch',
                        'This socket can only submit turns for the player and session it joined with.',
                        {
                            'bound_session_id': bound_session_id,
                            'bound_player_id': bound_player_id,
                        },
                    ),
                )
                telemetry_event(
                    'socket.send_message.player_identity_mismatch',
                    payload={
                        'sid': request.sid,
                        'session_id': session_id,
                        'player_id': player_id,
                        'bound_session_id': bound_session_id,
                        'bound_player_id': bound_player_id,
                    },
                    severity='warning',
                )
                return

            rate_key = f"{request.sid}:{session_id}"
            limit_result = _socket_rate_limiter().allow(rate_key)
            if not limit_result.allowed:
                emit(
                    'error',
                    socket_error(
                        'rate_limited',
                        'Too many socket messages; please wait before sending more.',
                        {'reset_in_seconds': limit_result.reset_in_seconds},
                    ),
                )
                telemetry_event(
                    'socket.send_message.rate_limited',
                    payload={'sid': request.sid, 'session_id': session_id, 'reset_in_seconds': limit_result.reset_in_seconds},
                    severity='warning',
                )
                return

            engine = TurnEngine(
                socketio=socketio,
                emit_fn=emit,
                stream_fn=query_dm_function_stream,
                latest_pending_turn_fn=_latest_pending_turn,
                dc_hint_from_turn_fn=_dc_hint_from_turn,
                apply_pending_resolution_hint_fn=_apply_pending_resolution_hint,
                build_roll_prompt_fn=_build_roll_prompt,
                response_mentions_roll_request_fn=_response_mentions_roll_request,
            )
            engine.process(
                TurnCommand(
                    sid=request.sid,
                    session_id=session_id,
                    campaign_id=campaign_id,
                    world_id=world_id,
                    player_id=player_id,
                    user_input=user_input,
                    manual_segment_ids=manual_segment_ids,
                )
            )
        finally:
            clear_logging_context()
