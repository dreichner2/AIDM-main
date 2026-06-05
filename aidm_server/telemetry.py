"""Telemetry client for local metrics and optional external event delivery."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time
import logging

import requests
from flask import current_app, has_app_context


logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TelemetryClient:
    def __init__(
        self,
        enabled: bool,
        endpoint: str | None,
        api_key: str | None,
        timeout_seconds: int,
        max_queue_size: int,
    ):
        self.enabled = bool(enabled)
        self.endpoint = (endpoint or '').strip()
        self.api_key = (api_key or '').strip() or None
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_queue_size = max(1, int(max_queue_size))

        self._lock = Lock()
        self._counters = Counter()
        self._timings = defaultdict(lambda: {'count': 0, 'sum_ms': 0.0, 'min_ms': None, 'max_ms': None})
        self._stop_event = Event()
        self._delivery_queue: Queue | None = None
        self._delivery_thread: Thread | None = None
        if self.enabled and self.endpoint:
            self._delivery_queue = Queue(maxsize=self.max_queue_size)
            self._delivery_thread = Thread(target=self._delivery_loop, name='aidm-telemetry', daemon=True)
            self._delivery_thread.start()

    def record_metric(self, name: str, value: int = 1, tags: dict | None = None):
        key = self._metric_key(name, tags)
        with self._lock:
            self._counters[key] += value
            self._counters['metrics.total'] += value

    def record_timing(self, name: str, value_ms: float, tags: dict | None = None):
        key = self._metric_key(name, tags)
        value = float(value_ms)
        with self._lock:
            bucket = self._timings[key]
            bucket['count'] += 1
            bucket['sum_ms'] += value
            bucket['min_ms'] = value if bucket['min_ms'] is None else min(bucket['min_ms'], value)
            bucket['max_ms'] = value if bucket['max_ms'] is None else max(bucket['max_ms'], value)
            self._counters['timings.total'] += 1

    def record_event(self, event_name: str, payload: dict | None = None, severity: str = 'info'):
        payload = payload or {}
        self.record_metric('events.total', 1)
        self.record_metric(f'event.{event_name}', 1)

        if not (self.enabled and self.endpoint):
            return

        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        event_body = {
            'event': event_name,
            'severity': severity,
            'payload': payload,
            'ts': _utc_now_iso(),
            'service': 'ai-dm',
        }

        if self._delivery_queue is None:
            self._deliver_event(event_name=event_name, event_body=event_body, headers=headers)
            return

        try:
            self._delivery_queue.put_nowait((event_name, event_body, headers))
        except Full:
            self.record_metric('telemetry.external.dropped', 1)
            logger.warning('Telemetry queue full; dropping event=%s', event_name)

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            timings = {
                key: {
                    'count': value['count'],
                    'avg_ms': (value['sum_ms'] / value['count']) if value['count'] else 0.0,
                    'min_ms': value['min_ms'],
                    'max_ms': value['max_ms'],
                    'sum_ms': value['sum_ms'],
                }
                for key, value in self._timings.items()
            }

        return {
            'enabled': self.enabled,
            'external_endpoint_configured': bool(self.endpoint),
            'counters': counters,
            'timings': timings,
        }

    def flush(self, timeout_seconds: float | None = None) -> bool:
        if self._delivery_queue is None:
            return True

        deadline = None if timeout_seconds is None else (time.monotonic() + max(0.0, timeout_seconds))
        while self._delivery_queue.unfinished_tasks:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def shutdown(self, timeout_seconds: float | None = None):
        if self._delivery_queue is None or self._delivery_thread is None:
            return
        self.flush(timeout_seconds=timeout_seconds)
        self._stop_event.set()
        self._delivery_thread.join(timeout=timeout_seconds)

    @staticmethod
    def _metric_key(name: str, tags: dict | None = None) -> str:
        tags = tags or {}
        if not tags:
            return name
        ordered = ','.join(f'{k}={tags[k]}' for k in sorted(tags))
        return f'{name}|{ordered}'

    def _delivery_loop(self):
        assert self._delivery_queue is not None
        while not self._stop_event.is_set() or self._delivery_queue.unfinished_tasks:
            try:
                event_name, event_body, headers = self._delivery_queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self._deliver_event(event_name=event_name, event_body=event_body, headers=headers)
            finally:
                self._delivery_queue.task_done()

    def _deliver_event(self, *, event_name: str, event_body: dict, headers: dict[str, str]):
        try:
            response = requests.post(
                self.endpoint,
                json=event_body,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            status_code = int(getattr(response, 'status_code', 0) or 0)
            if 200 <= status_code < 300:
                self.record_metric('telemetry.external.sent', 1)
                return
            self.record_metric('telemetry.external.failed', 1)
            logger.warning('Telemetry delivery failed for event=%s: status=%s', event_name, status_code)
        except Exception as exc:
            self.record_metric('telemetry.external.failed', 1)
            logger.warning('Telemetry delivery failed for event=%s: %s', event_name, str(exc))


def init_telemetry(app):
    app.extensions['aidm_telemetry'] = TelemetryClient(
        enabled=app.config.get('AIDM_TELEMETRY_ENABLED', False),
        endpoint=app.config.get('AIDM_TELEMETRY_ENDPOINT'),
        api_key=app.config.get('AIDM_TELEMETRY_API_KEY'),
        timeout_seconds=app.config.get('AIDM_TELEMETRY_TIMEOUT_SECONDS', 2),
        max_queue_size=app.config.get('AIDM_TELEMETRY_MAX_QUEUE_SIZE', 1000),
    )


def get_telemetry() -> TelemetryClient | None:
    if not has_app_context():
        return None
    return current_app.extensions.get('aidm_telemetry')


def telemetry_metric(name: str, value: int = 1, tags: dict | None = None):
    client = get_telemetry()
    if client:
        client.record_metric(name, value=value, tags=tags)


def telemetry_timing(name: str, value_ms: float, tags: dict | None = None):
    client = get_telemetry()
    if client:
        client.record_timing(name, value_ms=value_ms, tags=tags)


def telemetry_event(event_name: str, payload: dict | None = None, severity: str = 'info'):
    client = get_telemetry()
    if client:
        client.record_event(event_name=event_name, payload=payload, severity=severity)
