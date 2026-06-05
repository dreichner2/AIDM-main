from __future__ import annotations

from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc)
