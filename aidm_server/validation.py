"""Common request validation helpers."""

from __future__ import annotations

from flask import Request


def parse_json_body(request: Request) -> dict | None:
    if not request.is_json:
        return None
    return request.get_json(silent=True)


def missing_fields(payload: dict | None, required_fields: list[str]) -> list[str]:
    if not isinstance(payload, dict):
        return list(required_fields)
    missing = []
    for field in required_fields:
        if payload.get(field) in (None, ''):
            missing.append(field)
    return missing


def coerce_int(value, default=None):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_bool(value, default=None):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'n', 'off'}:
            return False
    return None
