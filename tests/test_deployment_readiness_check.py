from __future__ import annotations

from pathlib import Path

import pytest

from scripts.deployment_readiness_check import (
    REQUIRED_SECURITY_HEADERS,
    merged_env,
    parse_env_file,
    validate_environment,
    validate_live_target,
)


def _ready_env(**overrides: str) -> dict[str, str]:
    env = {
        'AIDM_ENV': 'production',
        'FLASK_SECRET_KEY': 'a' * 40,
        'AIDM_AUTH_REQUIRED': 'true',
        'AIDM_API_AUTH_TOKENS': 'closed-beta-token',
        'AIDM_AUTO_CREATE_SCHEMA': 'false',
        'AIDM_RATE_LIMIT_STORE': 'database',
        'AIDM_TURN_COORDINATOR_STORE': 'database',
        'AIDM_CORS_ALLOWLIST': 'https://aidm.example.test',
        'AIDM_SOCKET_CORS_ALLOWLIST': 'https://aidm.example.test',
        'AIDM_SOCKETIO_WORKER_MODEL': 'single',
        'AIDM_OBSERVABILITY_PROVIDER': 'managed-prometheus',
        'AIDM_ALERT_OWNER': 'beta-oncall',
        'AIDM_TELEMETRY_ENABLED': 'true',
        'AIDM_TELEMETRY_ENDPOINT': 'https://telemetry.example.test/ingest',
        'AIDM_SECURITY_HEADERS_ENABLED': 'true',
        'AIDM_ACCOUNT_COOKIE_AUTH_ENABLED': 'true',
        'AIDM_ACCOUNT_COOKIE_SECURE': 'true',
        'AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED': 'false',
        'AIDM_LLM_PROVIDER': 'gemini',
    }
    env.update(overrides)
    return env


def test_parse_env_file_supports_comments_export_and_quotes(tmp_path: Path):
    env_file = tmp_path / '.env.production'
    env_file.write_text(
        """
        # hosted beta
        export AIDM_ENV=production
        FLASK_SECRET_KEY="quoted secret"
        AIDM_ALERT_OWNER='beta-oncall'
        """,
        encoding='utf-8',
    )

    assert parse_env_file(env_file) == {
        'AIDM_ENV': 'production',
        'FLASK_SECRET_KEY': 'quoted secret',
        'AIDM_ALERT_OWNER': 'beta-oncall',
    }


def test_merged_env_file_overrides_base_env(tmp_path: Path):
    env_file = tmp_path / '.env.production'
    env_file.write_text('AIDM_ENV=production\n', encoding='utf-8')

    assert merged_env(env_file, base_env={'AIDM_ENV': 'development'})['AIDM_ENV'] == 'production'


def test_validate_environment_accepts_hosted_closed_beta_config():
    report = validate_environment(_ready_env())

    assert report.ok
    assert any('exactly one backend worker' in warning for warning in report.warnings)


def test_validate_environment_rejects_placeholders_and_wildcard_cors():
    report = validate_environment(
        _ready_env(
            FLASK_SECRET_KEY='replace-with-secret',
            AIDM_CORS_ALLOWLIST='*',
            AIDM_SOCKET_CORS_ALLOWLIST='*',
            AIDM_OBSERVABILITY_PROVIDER='replace-with-provider-name',
        )
    )

    assert not report.ok
    assert any('FLASK_SECRET_KEY still looks like a placeholder' in error for error in report.errors)
    assert any('Wildcard CORS' in error for error in report.errors)
    assert any('AIDM_OBSERVABILITY_PROVIDER still looks like a placeholder' in error for error in report.errors)


def test_validate_environment_requires_cookie_auth_or_documented_exception():
    missing_cookie_report = validate_environment(
        _ready_env(
            AIDM_ACCOUNT_COOKIE_AUTH_ENABLED='false',
            AIDM_ACCOUNT_COOKIE_SECURE='false',
            AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED='true',
        )
    )
    exception_report = validate_environment(
        _ready_env(
            AIDM_ACCOUNT_COOKIE_AUTH_ENABLED='false',
            AIDM_ACCOUNT_COOKIE_SECURE='false',
            AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED='true',
        ),
        auth_storage_exception='Native API clients use bearer tokens only.',
    )

    assert not missing_cookie_report.ok
    assert any('AIDM_ACCOUNT_COOKIE_AUTH_ENABLED=true' in error for error in missing_cookie_report.errors)
    assert exception_report.ok


def test_validate_environment_requires_socketio_proof_for_multi_worker_models():
    sticky_report = validate_environment(_ready_env(AIDM_SOCKETIO_WORKER_MODEL='sticky'))
    queue_report = validate_environment(
        _ready_env(
            AIDM_SOCKETIO_WORKER_MODEL='message_queue',
            AIDM_SOCKETIO_MESSAGE_QUEUE='redis://redis.example.test:6379/0',
        ),
        socketio_staging_proof='staging browser-smoke run 123',
    )

    assert not sticky_report.ok
    assert any('sticky Socket.IO deployments require --socketio-staging-proof' in error for error in sticky_report.errors)
    assert queue_report.ok


class _FakeResponse:
    def __init__(self, *, payload=None, text='', headers=None):
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_validate_live_target_checks_health_metrics_prometheus_and_headers(monkeypatch):
    security_headers = {header: 'set' for header in REQUIRED_SECURITY_HEADERS}

    def fake_get(url, headers, timeout):
        assert headers == {'Authorization': 'Bearer live-token'}
        assert timeout == 4
        if url.endswith('/api/health'):
            return _FakeResponse(
                payload={
                    'status': 'ok',
                    'env': 'production',
                    'auth_required': True,
                    'llm': {'provider': 'gemini'},
                },
                headers=security_headers,
            )
        if url.endswith('/api/metrics'):
            return _FakeResponse(payload={'counters': {}, 'timings': {}, 'beta': {}})
        if url.endswith('/api/metrics/prometheus'):
            return _FakeResponse(
                text='# TYPE aidm_telemetry_enabled gauge\naidm_telemetry_enabled 1\naidm_beta_bad_turn_reports 0\n',
                headers={'Content-Type': 'text/plain; version=0.0.4'},
            )
        raise AssertionError(url)

    monkeypatch.setattr('scripts.deployment_readiness_check.requests.get', fake_get)

    report = validate_live_target('https://aidm.example.test', auth_token='live-token', timeout_seconds=4)

    assert report.ok


def test_validate_live_target_rejects_missing_security_headers(monkeypatch):
    def fake_get(url, headers, timeout):
        del headers, timeout
        if url.endswith('/api/health'):
            return _FakeResponse(
                payload={
                    'status': 'ok',
                    'env': 'production',
                    'auth_required': True,
                    'llm': {'provider': 'gemini'},
                },
                headers={},
            )
        if url.endswith('/api/metrics'):
            return _FakeResponse(payload={'counters': {}, 'timings': {}, 'beta': {}})
        if url.endswith('/api/metrics/prometheus'):
            return _FakeResponse(
                text='# TYPE aidm_telemetry_enabled gauge\naidm_telemetry_enabled 1\naidm_beta_bad_turn_reports 0\n',
                headers={'Content-Type': 'text/plain'},
            )
        raise AssertionError(url)

    monkeypatch.setattr('scripts.deployment_readiness_check.requests.get', fake_get)

    report = validate_live_target('https://aidm.example.test')

    assert not report.ok
    assert any('missing security headers' in error for error in report.errors)


def test_parse_env_file_rejects_invalid_lines(tmp_path: Path):
    env_file = tmp_path / '.env.production'
    env_file.write_text('AIDM_ENV production\n', encoding='utf-8')

    with pytest.raises(ValueError, match='expected KEY=value'):
        parse_env_file(env_file)
