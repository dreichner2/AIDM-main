from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aidm_server.rate_limiter as rate_limiter_module


class _FrozenDateTime:
    current = datetime(2026, 1, 1, tzinfo=timezone.utc)
    min = datetime.min

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def test_rate_limiter_sweeps_expired_keys(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, 'datetime', _FrozenDateTime)
    limiter = rate_limiter_module.FixedWindowRateLimiter(limit=1, window_seconds=10)

    for index in range(25):
        assert limiter.allow(f'key-{index}').allowed is True
    assert len(limiter._events) == 25

    _FrozenDateTime.current = _FrozenDateTime.current + timedelta(seconds=11)

    result = limiter.allow('fresh-key')
    assert result.allowed is True
    assert set(limiter._events) == {'fresh-key'}
