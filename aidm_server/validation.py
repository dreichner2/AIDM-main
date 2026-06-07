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
    if isinstance(value, bool):
        return default
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


def optional_text(value, *, max_length: int, field: str, default: str | None = ''):
    if value is None:
        return default, None
    if not isinstance(value, str):
        return None, f'{field} must be a string.'
    text = value.strip()
    if len(text) > max_length:
        return None, f'{field} must be {max_length} characters or fewer.'
    return text, None


def required_text(value, *, max_length: int, field: str):
    text, error = optional_text(value, max_length=max_length, field=field, default='')
    if error:
        return None, error
    if not text:
        return None, f'{field} is required.'
    return text, None


def positive_int(value, *, field: str, required: bool = False, default: int | None = None):
    if value in (None, ''):
        if required:
            return None, f'{field} is required.'
        return default, None
    coerced = coerce_int(value)
    if coerced is None or coerced < 1:
        return None, f'{field} must be a positive integer.'
    return coerced, None


def json_object(value, *, field: str, default: dict | None = None):
    if value is None:
        return ({} if default is None else default), None
    if not isinstance(value, dict):
        return None, f'{field} must be a JSON object.'
    return value, None
