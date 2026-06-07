"""Socket.IO runtime helpers outside the transport registration module."""

from __future__ import annotations

from typing import Any, Callable

from flask import current_app, request

from aidm_server.auth import DEFAULT_WORKSPACE_ID, extract_socket_token, is_token_authorized, workspace_id_for_token
from aidm_server.logging_context import new_correlation_id, set_logging_context
from aidm_server.rate_limiter import FixedWindowRateLimiter, build_rate_limiter
from aidm_server.socket_state import SocketState
from aidm_server.validation import coerce_int

EmitFn = Callable[..., Any]
LeaveRoomFn = Callable[[str], Any]


class SocketRuntime:
    def __init__(self, state: SocketState):
        self.state = state
        self._limiter: FixedWindowRateLimiter | None = None
        self._limiter_config: tuple[int, int, str] | None = None

    def set_context(self, event_name: str, data: dict | None = None, turn_id: int | None = None) -> None:
        sid = getattr(request, 'sid', 'unknown')
        connection = self.state.connection(sid) or {}
        correlation_id = (
            (data or {}).get('correlation_id')
            or connection.get('correlation_id')
            or new_correlation_id(prefix=f'socket-{event_name}')
        )
        session_id = (data or {}).get('session_id') or connection.get('session_id')

        set_logging_context(correlation_id=correlation_id, session_id=session_id, turn_id=turn_id)
        if sid:
            connection['correlation_id'] = correlation_id
            self.state.set_connection(sid, connection)

    def rate_limiter(self) -> FixedWindowRateLimiter:
        limit = int(current_app.config.get('AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES', 40))
        window_seconds = int(current_app.config.get('AIDM_RATE_LIMIT_WINDOW_SECONDS', 30))
        store_name = str(current_app.config.get('AIDM_RATE_LIMIT_STORE', 'memory')).strip().lower()
        limiter_config = (limit, window_seconds, store_name)

        if self._limiter is None or self._limiter_config != limiter_config:
            self._limiter = build_rate_limiter(
                limit=limit,
                window_seconds=window_seconds,
                store_name=store_name,
            )
            self._limiter_config = limiter_config
        return self._limiter

    def auth_required(self) -> bool:
        try:
            return bool(current_app.config.get('AIDM_AUTH_REQUIRED', False))
        except Exception:
            return False

    def is_authorized(self, auth_payload: dict | None = None, data_payload: dict | None = None) -> bool:
        if not self.auth_required():
            return True
        sid = getattr(request, 'sid', None)
        existing = self.state.connection(sid)
        if existing and existing.get('authorized'):
            return True
        token = extract_socket_token(auth_payload=auth_payload, data_payload=data_payload)
        return is_token_authorized(token)

    def workspace_id_for_auth(self, auth_payload: dict | None = None, data_payload: dict | None = None) -> str | None:
        if not self.auth_required():
            return DEFAULT_WORKSPACE_ID
        sid = getattr(request, 'sid', None)
        existing = self.state.connection(sid)
        if existing and existing.get('authorized'):
            return str(existing.get('workspace_id') or DEFAULT_WORKSPACE_ID)
        token = extract_socket_token(auth_payload=auth_payload, data_payload=data_payload)
        return workspace_id_for_token(token)

    def active_player_payloads(self, session_id: int) -> list[dict]:
        return self.state.active_player_payloads(session_id)

    def track_active_player(self, session_id: int, player_data: dict, sid: str) -> bool:
        return self.state.track_active_player(session_id, player_data, sid)

    def release_active_player(self, session_id: int, player_id: int, sid: str) -> bool:
        return self.state.release_active_player(session_id, player_id, sid)

    def clear_connection_binding(
        self,
        sid: str,
        *,
        leave_bound_room: bool,
        leave_room_fn: LeaveRoomFn,
        emit_fn: EmitFn,
    ) -> dict[str, Any] | None:
        connection_record = self.state.connection(sid)
        if not connection_record:
            return None

        session_id = coerce_int(connection_record.get('session_id'))
        player_id = coerce_int(connection_record.get('player_id'))
        if leave_bound_room and session_id:
            leave_room_fn(str(session_id))
        if session_id and player_id and self.release_active_player(session_id, player_id, sid):
            emit_fn('player_left', {'id': player_id}, room=str(session_id))
            emit_fn('active_players', self.active_player_payloads(session_id), room=str(session_id))
        connection_record['session_id'] = None
        connection_record['player_id'] = None
        return connection_record

    def release_disconnect(self, sid: str, *, emit_fn: EmitFn) -> dict[str, Any] | None:
        connection_info = self.state.pop_connection(sid)
        if not connection_info:
            return None

        session_id = coerce_int(connection_info.get('session_id'))
        player_id = coerce_int(connection_info.get('player_id'))
        set_logging_context(session_id=session_id)

        if session_id and player_id and self.release_active_player(session_id, player_id, sid):
            emit_fn('player_left', {'id': player_id}, room=str(session_id))
            emit_fn('active_players', self.active_player_payloads(session_id), room=str(session_id))
        return connection_info
