from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock, RLock
import time


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


session_turn_coordinator = SessionTurnCoordinator()
