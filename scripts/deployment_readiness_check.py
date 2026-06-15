from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from typing import Mapping
from urllib.parse import urljoin

import requests


SUPPORTED_SOCKETIO_WORKER_MODELS = {'single', 'sticky', 'message_queue'}
PLACEHOLDER_MARKERS = (
    '<',
    '>',
    'changeme',
    'example.com',
    'placeholder',
    'replace-',
    'replace_',
    'replace with',
    'replace-with',
)
REQUIRED_SECURITY_HEADERS = {
    'Content-Security-Policy',
    'X-Content-Type-Options',
    'X-Frame-Options',
    'Referrer-Policy',
    'Permissions-Policy',
}


@dataclass
class ReadinessReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export ') :].strip()
        if '=' not in line:
            raise ValueError(f'{path}:{line_number}: expected KEY=value.')
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f'{path}:{line_number}: empty environment key.')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def merged_env(env_file: Path | None, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    if env_file:
        env.update(parse_env_file(env_file))
    return env


def _normalized_bool(value: str | None) -> str:
    return str(value or '').strip().lower()


def _is_true(value: str | None) -> bool:
    return _normalized_bool(value) in {'1', 'true', 'yes', 'on'}


def _is_false(value: str | None) -> bool:
    return _normalized_bool(value) in {'0', 'false', 'no', 'off'}


def _split_list(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or '').split(',') if item.strip()]


def _looks_placeholder(value: str | None) -> bool:
    normalized = str(value or '').strip().lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def _required_value(report: ReadinessReport, env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key) or '').strip()
    if not value:
        report.error(f'{key} is required.')
    elif _looks_placeholder(value):
        report.error(f'{key} still looks like a placeholder.')
    return value


def _validate_bool(
    report: ReadinessReport,
    env: Mapping[str, str],
    key: str,
    *,
    expected: bool,
    message: str,
) -> None:
    value = env.get(key)
    if expected and not _is_true(value):
        report.error(message)
    elif not expected and not _is_false(value):
        report.error(message)


def validate_environment(
    env: Mapping[str, str],
    *,
    same_origin_deployment: bool = False,
    auth_storage_exception: str = '',
    socketio_staging_proof: str = '',
    allow_fallback_provider: bool = False,
) -> ReadinessReport:
    report = ReadinessReport()

    if str(env.get('AIDM_ENV') or '').strip().lower() != 'production':
        report.error('AIDM_ENV must be production for hosted closed-beta readiness.')
    _required_value(report, env, 'FLASK_SECRET_KEY')
    if len(str(env.get('FLASK_SECRET_KEY') or '')) < 32:
        report.error('FLASK_SECRET_KEY must be at least 32 characters.')

    _validate_bool(
        report,
        env,
        'AIDM_AUTH_REQUIRED',
        expected=True,
        message='AIDM_AUTH_REQUIRED must be true for hosted closed-beta readiness.',
    )
    tokens = _split_list(env.get('AIDM_API_AUTH_TOKENS'))
    token_workspaces = _split_list(env.get('AIDM_API_AUTH_TOKEN_WORKSPACES'))
    if not tokens and not token_workspaces:
        report.error('AIDM_API_AUTH_TOKENS or AIDM_API_AUTH_TOKEN_WORKSPACES must be configured.')
    for key in ('AIDM_API_AUTH_TOKENS', 'AIDM_API_AUTH_TOKEN_WORKSPACES'):
        value = str(env.get(key) or '').strip()
        if value and _looks_placeholder(value):
            report.error(f'{key} still looks like a placeholder.')

    _validate_bool(
        report,
        env,
        'AIDM_AUTO_CREATE_SCHEMA',
        expected=False,
        message='AIDM_AUTO_CREATE_SCHEMA must be false; migrations must own schema changes.',
    )
    if str(env.get('AIDM_RATE_LIMIT_STORE') or '').strip().lower() != 'database':
        report.error('AIDM_RATE_LIMIT_STORE must be database for hosted/multi-worker readiness.')
    if str(env.get('AIDM_TURN_COORDINATOR_STORE') or '').strip().lower() != 'database':
        report.error('AIDM_TURN_COORDINATOR_STORE must be database for hosted/multi-worker readiness.')

    rest_cors = _split_list(env.get('AIDM_CORS_ALLOWLIST'))
    socket_cors = _split_list(env.get('AIDM_SOCKET_CORS_ALLOWLIST'))
    if '*' in rest_cors or '*' in socket_cors:
        report.error('Wildcard CORS allowlists are not allowed for hosted closed-beta readiness.')
    if not same_origin_deployment and (not rest_cors or not socket_cors):
        report.error(
            'AIDM_CORS_ALLOWLIST and AIDM_SOCKET_CORS_ALLOWLIST must be explicit, '
            'or pass --same-origin-deployment for an intentionally same-origin target.'
        )

    worker_model = str(env.get('AIDM_SOCKETIO_WORKER_MODEL') or '').strip().lower().replace('-', '_')
    if worker_model not in SUPPORTED_SOCKETIO_WORKER_MODELS:
        expected = ', '.join(sorted(SUPPORTED_SOCKETIO_WORKER_MODELS))
        report.error(f'AIDM_SOCKETIO_WORKER_MODEL must be one of: {expected}.')
    elif worker_model == 'message_queue':
        if _looks_placeholder(env.get('AIDM_SOCKETIO_MESSAGE_QUEUE')):
            report.error('AIDM_SOCKETIO_WORKER_MODEL=message_queue requires AIDM_SOCKETIO_MESSAGE_QUEUE.')
        if not socketio_staging_proof.strip():
            report.error('message_queue Socket.IO deployments require --socketio-staging-proof.')
    elif worker_model == 'sticky':
        if not socketio_staging_proof.strip():
            report.error('sticky Socket.IO deployments require --socketio-staging-proof.')
    elif worker_model == 'single':
        report.warn('AIDM_SOCKETIO_WORKER_MODEL=single requires exactly one backend worker in deployment.')

    _required_value(report, env, 'AIDM_OBSERVABILITY_PROVIDER')
    _required_value(report, env, 'AIDM_ALERT_OWNER')
    if _is_true(env.get('AIDM_TELEMETRY_ENABLED')):
        _required_value(report, env, 'AIDM_TELEMETRY_ENDPOINT')
    else:
        report.warn('AIDM_TELEMETRY_ENABLED is not true; confirm managed metrics scraping covers beta SLOs.')

    _validate_bool(
        report,
        env,
        'AIDM_SECURITY_HEADERS_ENABLED',
        expected=True,
        message='AIDM_SECURITY_HEADERS_ENABLED must be true.',
    )

    cookie_auth_enabled = _is_true(env.get('AIDM_ACCOUNT_COOKIE_AUTH_ENABLED'))
    if cookie_auth_enabled:
        _validate_bool(
            report,
            env,
            'AIDM_ACCOUNT_COOKIE_SECURE',
            expected=True,
            message='AIDM_ACCOUNT_COOKIE_SECURE must be true when cookie auth is enabled.',
        )
        _validate_bool(
            report,
            env,
            'AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED',
            expected=False,
            message='AIDM_ACCOUNT_TOKEN_RESPONSE_ENABLED must be false for cookie-only hosted browser auth.',
        )
    elif not auth_storage_exception.strip():
        report.error(
            'Hosted readiness requires AIDM_ACCOUNT_COOKIE_AUTH_ENABLED=true, '
            'or --auth-storage-exception documenting why bearer/session storage is acceptable.'
        )

    provider = str(env.get('AIDM_LLM_PROVIDER') or '').strip().lower()
    if provider == 'fallback' and not allow_fallback_provider:
        report.error('AIDM_LLM_PROVIDER=fallback is safe-mode only; pass --allow-fallback-provider for intentional drills.')

    return report


def _request_json(url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[dict, requests.Response]:
    response = requests.get(url, headers=dict(headers), timeout=timeout_seconds)
    response.raise_for_status()
    return response.json(), response


def _request_text(url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[str, requests.Response]:
    response = requests.get(url, headers=dict(headers), timeout=timeout_seconds)
    response.raise_for_status()
    return response.text, response


def validate_live_target(
    target_url: str,
    *,
    auth_token: str = '',
    timeout_seconds: float = 10.0,
    allow_fallback_provider: bool = False,
    allow_non_production_target: bool = False,
) -> ReadinessReport:
    report = ReadinessReport()
    base_url = target_url.rstrip('/') + '/'
    headers = {'Authorization': f'Bearer {auth_token}'} if auth_token else {}

    try:
        health, health_response = _request_json(urljoin(base_url, 'api/health'), headers, timeout_seconds)
    except Exception as exc:  # pragma: no cover - exact requests exception type is not useful to assert.
        report.error(f'GET /api/health failed: {exc}')
        return report

    if health.get('status') != 'ok':
        report.error('GET /api/health did not return status=ok.')
    if health.get('auth_required') is not True:
        report.error('GET /api/health reports auth_required is not true.')
    if health.get('env') != 'production' and not allow_non_production_target:
        report.error('GET /api/health does not report env=production.')
    llm_payload = health.get('llm') if isinstance(health.get('llm'), dict) else {}
    if str(llm_payload.get('provider') or '').lower() == 'fallback' and not allow_fallback_provider:
        report.error('GET /api/health reports the deterministic fallback provider.')

    missing_headers = [header for header in sorted(REQUIRED_SECURITY_HEADERS) if not health_response.headers.get(header)]
    if missing_headers:
        report.error(f'GET /api/health is missing security headers: {", ".join(missing_headers)}.')

    try:
        metrics, _metrics_response = _request_json(urljoin(base_url, 'api/metrics'), headers, timeout_seconds)
    except Exception as exc:  # pragma: no cover - exact requests exception type is not useful to assert.
        report.error(f'GET /api/metrics failed: {exc}')
    else:
        if not isinstance(metrics.get('counters'), dict) or not isinstance(metrics.get('timings'), dict):
            report.error('GET /api/metrics payload is missing counters/timings objects.')
        if not isinstance(metrics.get('beta'), dict):
            report.error('GET /api/metrics payload is missing beta summary gauges.')

    try:
        prometheus_text, prometheus_response = _request_text(
            urljoin(base_url, 'api/metrics/prometheus'),
            headers,
            timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - exact requests exception type is not useful to assert.
        report.error(f'GET /api/metrics/prometheus failed: {exc}')
    else:
        content_type = prometheus_response.headers.get('Content-Type', '')
        if not content_type.startswith('text/plain'):
            report.error('GET /api/metrics/prometheus did not return text/plain content.')
        if 'aidm_telemetry_enabled' not in prometheus_text:
            report.error('GET /api/metrics/prometheus is missing aidm_telemetry_enabled.')
        if 'aidm_beta_' not in prometheus_text:
            report.error('GET /api/metrics/prometheus is missing beta gauges.')

    return report


def _merge_reports(*reports: ReadinessReport) -> ReadinessReport:
    merged = ReadinessReport()
    for report in reports:
        merged.errors.extend(report.errors)
        merged.warnings.extend(report.warnings)
    return merged


def _print_report(report: ReadinessReport) -> None:
    for warning in report.warnings:
        print(f'[deployment-readiness][warning] {warning}')
    for error in report.errors:
        print(f'[deployment-readiness][error] {error}')
    if report.ok:
        print('[deployment-readiness] All checks passed.')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Validate hosted closed-beta deployment readiness.')
    parser.add_argument('--env-file', type=Path, help='Optional production env file to validate.')
    parser.add_argument('--target-url', help='Optional deployed target base URL for live endpoint checks.')
    parser.add_argument('--auth-token', help='Bearer token for live target checks when auth is required.')
    parser.add_argument('--timeout-seconds', type=float, default=10.0, help='HTTP timeout for live target checks.')
    parser.add_argument(
        '--same-origin-deployment',
        action='store_true',
        help='Allow empty CORS allowlists because the deployment is intentionally same-origin.',
    )
    parser.add_argument(
        '--auth-storage-exception',
        default='',
        help='Document why hosted browser auth is not using HTTP-only cookies.',
    )
    parser.add_argument(
        '--socketio-staging-proof',
        default='',
        help='Required note/URL proving sticky or message-queue Socket.IO delivery in staging.',
    )
    parser.add_argument(
        '--allow-fallback-provider',
        action='store_true',
        help='Allow the deterministic fallback provider for explicit safe-mode drills.',
    )
    parser.add_argument(
        '--allow-non-production-target',
        action='store_true',
        help='Allow live endpoint checks against a staging target that does not report env=production.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        env = merged_env(args.env_file)
    except Exception as exc:
        print(f'[deployment-readiness][error] {exc}')
        return 1

    reports = [
        validate_environment(
            env,
            same_origin_deployment=args.same_origin_deployment,
            auth_storage_exception=args.auth_storage_exception,
            socketio_staging_proof=args.socketio_staging_proof,
            allow_fallback_provider=args.allow_fallback_provider,
        )
    ]
    if args.target_url:
        reports.append(
            validate_live_target(
                args.target_url,
                auth_token=args.auth_token or '',
                timeout_seconds=args.timeout_seconds,
                allow_fallback_provider=args.allow_fallback_provider,
                allow_non_production_target=args.allow_non_production_target,
            )
        )

    report = _merge_reports(*reports)
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
