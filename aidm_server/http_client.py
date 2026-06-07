"""Shared HTTP client helpers for provider integrations."""

from __future__ import annotations

import atexit
import os
from threading import Lock
from time import perf_counter
from typing import Any

from flask import current_app, has_app_context
import requests

from aidm_server.telemetry import telemetry_metric, telemetry_timing

_sessions: dict[str, requests.Session] = {}
_sessions_lock = Lock()


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _config_or_env(name: str, default: float) -> float:
    if has_app_context():
        value = current_app.config.get(name)
        if value is not None:
            return _positive_float(value, default)
    return _positive_float(os.getenv(name), default)


def timeout_from_config(prefix: str, *, default_connect: float, default_read: float) -> tuple[float, float]:
    """Return a requests timeout tuple from `<prefix>_CONNECT/READ_TIMEOUT_SECONDS`.

    A tuple keeps connect failures separate from slow response bodies, which is
    important for streamed provider calls where the read phase can legitimately
    last much longer than the TCP/TLS handshake.
    """
    connect_timeout = _config_or_env(f'{prefix}_CONNECT_TIMEOUT_SECONDS', default_connect)
    read_timeout = _config_or_env(f'{prefix}_READ_TIMEOUT_SECONDS', default_read)
    return connect_timeout, read_timeout


def get_http_session(client_name: str) -> requests.Session:
    key = str(client_name or 'default').strip().lower() or 'default'
    with _sessions_lock:
        session = _sessions.get(key)
        if session is None:
            session = requests.Session()
            _sessions[key] = session
        return session


def close_http_sessions():
    with _sessions_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.close()


def post(client_name: str, url: str, **kwargs) -> requests.Response:
    session = get_http_session(client_name)
    tags = {'client': str(client_name or 'default')}
    telemetry_metric('http.post.requests_total', 1, tags=tags)
    started_at = perf_counter()
    try:
        response = session.post(url, **kwargs)
    except Exception:
        telemetry_metric('http.post.exceptions_total', 1, tags=tags)
        raise
    finally:
        telemetry_timing('http.post.duration_ms', (perf_counter() - started_at) * 1000, tags=tags)
    return response


atexit.register(close_http_sessions)
