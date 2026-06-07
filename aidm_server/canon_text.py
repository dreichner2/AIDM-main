"""Small normalization helpers shared by canon/memory modules."""

from __future__ import annotations

import re
from typing import Any


def normalized_name(value: str | None) -> str:
    text = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()
    return re.sub(r'\s+', ' ', text)


def int_or_default(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def positive_int(value: Any, default: int = 1) -> int:
    return max(1, int_or_default(value, default))


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
