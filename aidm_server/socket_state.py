"""In-process Socket.IO presence and connection state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SocketState:
    active_players: dict[int, dict[int, dict[str, Any]]] = field(default_factory=dict)
    connections: dict[str, dict[str, Any]] = field(default_factory=dict)

    def connection(self, sid: str | None) -> dict[str, Any] | None:
        if not sid:
            return None
        return self.connections.get(sid)

    def ensure_connection(self, sid: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.connections.setdefault(sid, defaults or {})

    def set_connection(self, sid: str, data: dict[str, Any]) -> None:
        self.connections[sid] = data

    def pop_connection(self, sid: str) -> dict[str, Any] | None:
        return self.connections.pop(sid, None)

    def active_player_payloads(self, session_id: int) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in player_data.items() if not key.startswith('_')}
            for player_data in self.active_players.get(session_id, {}).values()
        ]

    def ensure_session(self, session_id: int) -> None:
        self.active_players.setdefault(session_id, {})

    def track_active_player(self, session_id: int, player_data: dict[str, Any], sid: str) -> bool:
        session_players = self.active_players.setdefault(session_id, {})
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

    def release_active_player(self, session_id: int, player_id: int, sid: str) -> bool:
        session_players = self.active_players.get(session_id)
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
            del self.active_players[session_id]
        return True

    def clear(self) -> None:
        self.active_players.clear()
        self.connections.clear()
