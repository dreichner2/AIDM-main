"""Structured logging context helpers."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4


_correlation_id_var: ContextVar[str] = ContextVar('aidm_correlation_id', default='-')
_session_id_var: ContextVar[str] = ContextVar('aidm_session_id', default='-')
_turn_id_var: ContextVar[str] = ContextVar('aidm_turn_id', default='-')


class LoggingContextFilter(logging.Filter):
    """Attach correlation/session/turn metadata to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id_var.get()
        record.session_id = _session_id_var.get()
        record.turn_id = _turn_id_var.get()
        return True


def configure_logging():
    """Configure root logging formatter and attach the context filter once."""
    root_logger = logging.getLogger()
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - '
        '[cid=%(correlation_id)s sid=%(session_id)s tid=%(turn_id)s] - %(message)s'
    )

    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO)

    context_filter = LoggingContextFilter()
    for handler in root_logger.handlers:
        if not any(isinstance(existing, LoggingContextFilter) for existing in handler.filters):
            handler.addFilter(context_filter)
        handler.setFormatter(formatter)


def new_correlation_id(prefix: str = 'aidm') -> str:
    return f'{prefix}-{uuid4().hex[:12]}'


def set_logging_context(
    correlation_id: str | None = None,
    session_id: int | str | None = None,
    turn_id: int | str | None = None,
):
    if correlation_id is not None:
        _correlation_id_var.set(str(correlation_id))
    if session_id is not None:
        _session_id_var.set(str(session_id))
    if turn_id is not None:
        _turn_id_var.set(str(turn_id))


def get_correlation_id() -> str:
    return _correlation_id_var.get()


def clear_logging_context():
    _correlation_id_var.set('-')
    _session_id_var.set('-')
    _turn_id_var.set('-')
