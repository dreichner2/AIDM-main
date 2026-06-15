from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVABILITY_DIR = REPO_ROOT / 'observability'
REQUIRED_FILES = (
    OBSERVABILITY_DIR / 'docker-compose.yml',
    OBSERVABILITY_DIR / 'prometheus.yml',
    OBSERVABILITY_DIR / 'grafana' / 'provisioning' / 'datasources' / 'prometheus.yml',
    OBSERVABILITY_DIR / 'grafana' / 'provisioning' / 'dashboards' / 'aidm.yml',
    OBSERVABILITY_DIR / 'grafana' / 'dashboards' / 'aidm-overview.json',
)
REQUIRED_DASHBOARD_METRICS = (
    'aidm_api_requests_total',
    'aidm_socket_send_message_latency_milliseconds_avg',
    'aidm_event_socket_send_message_failed',
    'aidm_beta_session_completion_rate',
    'aidm_beta_coherence_feedback_avg',
)


class ObservabilityBundleError(RuntimeError):
    pass


def _read(path: Path) -> str:
    if not path.exists():
        raise ObservabilityBundleError(f'Missing required observability file: {path.relative_to(REPO_ROOT)}')
    if not path.is_file():
        raise ObservabilityBundleError(f'Observability path is not a file: {path.relative_to(REPO_ROOT)}')
    return path.read_text(encoding='utf-8')


def _require_contains(text: str, needle: str, *, label: str) -> None:
    if needle not in text:
        raise ObservabilityBundleError(f'{label} is missing {needle!r}.')


def _dashboard_expressions(dashboard: dict) -> list[str]:
    expressions: list[str] = []
    for panel in dashboard.get('panels') or []:
        if not isinstance(panel, dict):
            continue
        for target in panel.get('targets') or []:
            if isinstance(target, dict) and isinstance(target.get('expr'), str):
                expressions.append(target['expr'])
    return expressions


def validate_static_bundle() -> list[str]:
    warnings: list[str] = []
    for path in REQUIRED_FILES:
        _read(path)

    compose_text = _read(OBSERVABILITY_DIR / 'docker-compose.yml')
    _require_contains(compose_text, 'prom/prometheus', label='observability/docker-compose.yml')
    _require_contains(compose_text, 'grafana/grafana', label='observability/docker-compose.yml')
    _require_contains(compose_text, './prometheus.yml:/etc/prometheus/prometheus.yml:ro', label='observability/docker-compose.yml')
    _require_contains(compose_text, './grafana/dashboards:/var/lib/grafana/dashboards:ro', label='observability/docker-compose.yml')

    prometheus_text = _read(OBSERVABILITY_DIR / 'prometheus.yml')
    _require_contains(prometheus_text, '/api/metrics/prometheus', label='observability/prometheus.yml')
    _require_contains(prometheus_text, 'host.docker.internal:5050', label='observability/prometheus.yml')

    datasource_text = _read(OBSERVABILITY_DIR / 'grafana' / 'provisioning' / 'datasources' / 'prometheus.yml')
    _require_contains(datasource_text, 'uid: Prometheus', label='grafana datasource provisioning')
    _require_contains(datasource_text, 'url: http://prometheus:9090', label='grafana datasource provisioning')

    dashboard_provider_text = _read(OBSERVABILITY_DIR / 'grafana' / 'provisioning' / 'dashboards' / 'aidm.yml')
    _require_contains(dashboard_provider_text, 'path: /var/lib/grafana/dashboards', label='grafana dashboard provisioning')

    dashboard = json.loads(_read(OBSERVABILITY_DIR / 'grafana' / 'dashboards' / 'aidm-overview.json'))
    if dashboard.get('title') != 'AIDM Beta Overview':
        raise ObservabilityBundleError('Grafana dashboard title must be AIDM Beta Overview.')
    panels = dashboard.get('panels')
    if not isinstance(panels, list) or not panels:
        raise ObservabilityBundleError('Grafana dashboard must contain at least one panel.')
    expressions = '\n'.join(_dashboard_expressions(dashboard))
    for metric in REQUIRED_DASHBOARD_METRICS:
        if metric not in expressions:
            raise ObservabilityBundleError(f'Grafana dashboard is missing metric {metric!r}.')

    return warnings


def validate_docker_compose_config(*, require_docker: bool = False) -> list[str]:
    warnings: list[str] = []
    docker = shutil.which('docker')
    if not docker:
        message = 'Docker is not installed; skipped `docker compose config`.'
        if require_docker:
            raise ObservabilityBundleError(message)
        warnings.append(message)
        return warnings

    result = subprocess.run(
        [docker, 'compose', '-f', str(OBSERVABILITY_DIR / 'docker-compose.yml'), 'config'],
        cwd=str(OBSERVABILITY_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or '').strip()
        raise ObservabilityBundleError(f'`docker compose config` failed: {output}')
    return warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Validate the local observability bundle.')
    parser.add_argument(
        '--check-docker-compose',
        action='store_true',
        help='Also run `docker compose config` when Docker is available.',
    )
    parser.add_argument(
        '--require-docker',
        action='store_true',
        help='Fail if Docker is unavailable while --check-docker-compose is set.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        warnings = validate_static_bundle()
        if args.check_docker_compose:
            warnings.extend(validate_docker_compose_config(require_docker=args.require_docker))
    except Exception as exc:
        print(f'[observability-check][error] {exc}')
        return 1

    for warning in warnings:
        print(f'[observability-check][warning] {warning}')
    print('[observability-check] All checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
