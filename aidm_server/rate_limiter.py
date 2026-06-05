"""Small in-memory fixed-window rate limiter."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_in_seconds: int


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque[datetime]] = {}
        self._lock = Lock()
        self._next_gc_at = datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _prune_queue(queue: deque[datetime], window_start: datetime):
        while queue and queue[0] < window_start:
            queue.popleft()

    def _collect_garbage(self, window_start: datetime):
        stale_keys: list[str] = []
        for key, queue in self._events.items():
            self._prune_queue(queue, window_start)
            if not queue:
                stale_keys.append(key)
        for key in stale_keys:
            self._events.pop(key, None)

    def allow(self, key: str) -> RateLimitResult:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=self.window_seconds)

        with self._lock:
            if now >= self._next_gc_at:
                self._collect_garbage(window_start)
                self._next_gc_at = now + timedelta(seconds=self.window_seconds)

            queue = self._events.get(key)
            if queue is None:
                queue = deque()
                self._events[key] = queue
            else:
                self._prune_queue(queue, window_start)

            if len(queue) >= self.limit:
                reset_at = queue[0] + timedelta(seconds=self.window_seconds)
                reset_in = max(0, int((reset_at - now).total_seconds()))
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_in_seconds=reset_in,
                )

            queue.append(now)
            remaining = max(0, self.limit - len(queue))
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                reset_in_seconds=self.window_seconds,
            )
