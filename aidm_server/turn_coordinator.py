from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Lock, RLock
import time
from uuid import uuid4

from flask import current_app, has_app_context
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from aidm_server.database import db
from aidm_server.time_utils import utc_now


TURN_COORDINATOR_STORE_MEMORY = 'memory'
TURN_COORDINATOR_STORE_DATABASE = 'database'


@dataclass
class _SessionLockEntry:
    lock: Lock = field(default_factory=Lock)
    active: int = 0
    last_used: float = field(default_factory=time.monotonic)


class SessionTurnCoordinator:
    def __init__(self, *, max_idle_seconds: float = 600.0, clock=time.monotonic):
        self._guard = RLock()
        self._locks: dict[int, _SessionLockEntry] = {}
        self._max_idle_seconds = max_idle_seconds
        self._clock = clock

    def _cleanup_idle_locked(self, now: float):
        cutoff = now - self._max_idle_seconds
        for tracked_session_id, entry in list(self._locks.items()):
            if entry.active == 0 and entry.last_used <= cutoff:
                self._locks.pop(tracked_session_id, None)

    def _entry_for_session(self, session_id: int) -> _SessionLockEntry:
        with self._guard:
            now = self._clock()
            self._cleanup_idle_locked(now)
            entry = self._locks.setdefault(session_id, _SessionLockEntry(last_used=now))
            entry.active += 1
            return entry

    @contextmanager
    def serialized(self, session_id: int):
        entry = self._entry_for_session(session_id)
        lock = entry.lock
        wait_started = time.perf_counter()
        lock.acquire()
        wait_ms = (time.perf_counter() - wait_started) * 1000.0
        try:
            yield wait_ms
        finally:
            lock.release()
            with self._guard:
                current = self._locks.get(session_id)
                if current is entry:
                    entry.active = max(0, entry.active - 1)
                    entry.last_used = self._clock()
                    self._cleanup_idle_locked(entry.last_used)

    def discard_session(self, session_id: int) -> bool:
        with self._guard:
            entry = self._locks.get(session_id)
            if entry is None:
                return False
            if entry.active > 0:
                return False
            self._locks.pop(session_id, None)
            return True

    def lock_count(self) -> int:
        with self._guard:
            return len(self._locks)


class DatabaseSessionTurnCoordinator:
    def __init__(
        self,
        *,
        lease_seconds: int = 900,
        poll_interval_seconds: float = 0.05,
        clock=utc_now,
    ):
        self.lease_seconds = max(30, int(lease_seconds))
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._clock = clock

    def _try_acquire(self, session_id: int, owner_token: str) -> bool:
        from aidm_server.models import SessionTurnLock

        table = SessionTurnLock.__table__
        now = self._clock()
        expires_at = now + timedelta(seconds=self.lease_seconds)
        values = {
            'owner_token': owner_token,
            'acquired_at': now,
            'expires_at': expires_at,
            'updated_at': now,
        }

        with db.engine.begin() as connection:
            result = connection.execute(
                update(table)
                .where(table.c.session_id == session_id)
                .where(or_(table.c.expires_at <= now, table.c.owner_token == owner_token))
                .values(**values)
            )
            if result.rowcount:
                return True

        try:
            with db.engine.begin() as connection:
                connection.execute(insert(table).values(session_id=session_id, **values))
            return True
        except IntegrityError:
            return False

    def _release(self, session_id: int, owner_token: str) -> None:
        from aidm_server.models import SessionTurnLock

        table = SessionTurnLock.__table__
        with db.engine.begin() as connection:
            connection.execute(
                delete(table).where(
                    table.c.session_id == session_id,
                    table.c.owner_token == owner_token,
                )
            )

    @contextmanager
    def serialized(self, session_id: int):
        owner_token = uuid4().hex
        wait_started = time.perf_counter()
        while not self._try_acquire(session_id, owner_token):
            time.sleep(self.poll_interval_seconds)
        wait_ms = (time.perf_counter() - wait_started) * 1000.0
        try:
            yield wait_ms
        finally:
            self._release(session_id, owner_token)

    def discard_session(self, session_id: int) -> bool:
        from aidm_server.models import SessionTurnLock

        table = SessionTurnLock.__table__
        now = self._clock()
        with db.engine.begin() as connection:
            result = connection.execute(
                delete(table).where(
                    table.c.session_id == session_id,
                    table.c.expires_at <= now,
                )
            )
            return bool(result.rowcount)

    def lock_count(self) -> int:
        from aidm_server.models import SessionTurnLock

        table = SessionTurnLock.__table__
        with db.engine.begin() as connection:
            return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


class ConfiguredSessionTurnCoordinator:
    def __init__(self):
        self._memory = SessionTurnCoordinator()

    def _active_coordinator(self):
        if has_app_context() and current_app.config.get('AIDM_TURN_COORDINATOR_STORE') == TURN_COORDINATOR_STORE_DATABASE:
            return DatabaseSessionTurnCoordinator(
                lease_seconds=current_app.config.get('AIDM_TURN_COORDINATOR_LOCK_TTL_SECONDS', 900),
                poll_interval_seconds=current_app.config.get('AIDM_TURN_COORDINATOR_POLL_INTERVAL_MS', 50) / 1000.0,
            )
        return self._memory

    @contextmanager
    def serialized(self, session_id: int):
        with self._active_coordinator().serialized(session_id) as wait_ms:
            yield wait_ms

    def discard_session(self, session_id: int) -> bool:
        return self._active_coordinator().discard_session(session_id)

    def lock_count(self) -> int:
        return self._active_coordinator().lock_count()


session_turn_coordinator = ConfiguredSessionTurnCoordinator()
