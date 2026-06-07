from __future__ import annotations

import importlib
from queue import Queue

from aidm_server.database import ensure_schema


class _FakeResponse:
    status_code = 200


def test_metrics_endpoint_exposes_counters(client):
    client.get('/api/health')
    response = client.get('/api/metrics')
    assert response.status_code == 200

    payload = response.get_json()
    counters = payload['counters']
    assert counters.get('system.health.requests_total', 0) >= 1
    assert payload['enabled'] is False


def test_prometheus_metrics_endpoint_exposes_counters_and_beta_gauges(client):
    client.get('/api/health')
    response = client.get('/api/metrics/prometheus')
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/plain; version=0.0.4')

    body = response.get_data(as_text=True)
    assert '# TYPE aidm_telemetry_enabled gauge' in body
    assert 'aidm_system_health_requests_total' in body
    assert 'aidm_system_metrics_prometheus_requests_total 1' in body
    assert 'aidm_api_requests_total{method="GET",path="/api/health"}' in body
    assert 'aidm_beta_ai_failure_rate 0' in body


def test_prometheus_text_sanitizes_metric_and_label_names():
    import aidm_server.telemetry as telemetry_module

    client = telemetry_module.TelemetryClient(
        enabled=False,
        endpoint=None,
        api_key=None,
        timeout_seconds=1,
        max_queue_size=8,
    )
    client.record_metric(
        'custom.metric-total',
        2,
        tags={'odd label': 'needs"escape\n'},
    )
    client.record_timing('provider.phase_ms', 12.5, tags={'provider': 'test'})

    body = client.prometheus_text()
    assert 'aidm_custom_metric_total{odd_label="needs\\"escape\\n"} 2' in body
    assert 'aidm_provider_phase_milliseconds_count{provider="test"} 1' in body
    assert 'aidm_provider_phase_milliseconds_sum{provider="test"} 12.5' in body


def test_external_telemetry_delivery(tmp_path, monkeypatch):
    db_path = tmp_path / 'telemetry.db'

    monkeypatch.setenv('AIDM_DATABASE_URI', f'sqlite:///{db_path}')
    monkeypatch.setenv('AIDM_AUTO_CREATE_SCHEMA', 'true')
    monkeypatch.setenv('AIDM_ENV', 'test')
    monkeypatch.setenv('AIDM_DEBUG', 'false')
    monkeypatch.setenv('AIDM_SOCKETIO_ASYNC_MODE', 'threading')
    monkeypatch.setenv('AIDM_TELEMETRY_ENABLED', 'true')
    monkeypatch.setenv('AIDM_TELEMETRY_ENDPOINT', 'https://example.telemetry.test/ingest')
    monkeypatch.setenv('AIDM_TELEMETRY_API_KEY', 'telemetry-secret')

    captured = {}

    def fake_post(url, json, headers, timeout):
        captured['url'] = url
        captured['json'] = json
        captured['headers'] = headers
        captured['timeout'] = timeout
        return _FakeResponse()

    import aidm_server.telemetry as telemetry_module
    monkeypatch.setattr(telemetry_module.requests, 'post', fake_post)

    import aidm_server.main as main_module
    main_module = importlib.reload(main_module)

    app = main_module.create_app()
    ensure_schema(app)
    with app.app_context():
        telemetry_client = telemetry_module.get_telemetry()
        telemetry_module.telemetry_event('integration.test', payload={'ok': True})
        telemetry_module.telemetry_metric('integration.metric', 3)
        assert telemetry_client is not None
        assert telemetry_client.flush(timeout_seconds=1.0) is True

        metrics = app.test_client().get('/api/metrics').get_json()

    assert captured['url'] == 'https://example.telemetry.test/ingest'
    assert captured['json']['event'] == 'integration.test'
    assert captured['headers']['Authorization'] == 'Bearer telemetry-secret'
    assert metrics['enabled'] is True
    assert metrics['counters'].get('integration.metric', 0) == 3


def test_external_telemetry_http_error_counts_as_failed(monkeypatch):
    class _FailureResponse:
        status_code = 500

    import aidm_server.telemetry as telemetry_module

    monkeypatch.setattr(telemetry_module.requests, 'post', lambda *args, **kwargs: _FailureResponse())
    client = telemetry_module.TelemetryClient(
        enabled=True,
        endpoint='https://example.telemetry.test/ingest',
        api_key=None,
        timeout_seconds=1,
        max_queue_size=8,
    )

    client.record_event('integration.failure', payload={'ok': False})
    assert client.flush(timeout_seconds=1.0) is True

    snapshot = client.snapshot()
    assert snapshot['counters'].get('telemetry.external.sent', 0) == 0
    assert snapshot['counters'].get('telemetry.external.failed', 0) == 1
    client.shutdown(timeout_seconds=1.0)


def test_external_telemetry_drops_events_when_queue_is_full(monkeypatch):
    import aidm_server.telemetry as telemetry_module

    monkeypatch.setattr(telemetry_module.Thread, 'start', lambda self: None)
    client = telemetry_module.TelemetryClient(
        enabled=True,
        endpoint='https://example.telemetry.test/ingest',
        api_key=None,
        timeout_seconds=1,
        max_queue_size=1,
    )
    client._delivery_queue = Queue(maxsize=1)
    client._delivery_queue.put(('held', {'event': 'held'}, {}))

    client.record_event('integration.queue_overflow', payload={'ok': False})

    snapshot = client.snapshot()
    assert snapshot['counters'].get('telemetry.external.dropped', 0) == 1
