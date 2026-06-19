#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DecisionPaths:
    decision_doc: Path = REPO_ROOT / 'docs' / 'socketio_worker_model.md'
    env_example: Path = REPO_ROOT / '.env.production.example'
    production_server_script: Path = REPO_ROOT / 'scripts' / 'run_production_server.sh'
    production_readiness_doc: Path = REPO_ROOT / 'docs' / 'production-readiness.md'
    beta_runbook: Path = REPO_ROOT / 'docs' / 'beta_runbook.md'


def _read(path: Path, errors: list[str]) -> str:
    if not path.exists():
        errors.append(f'{path} is missing.')
        return ''
    return path.read_text(encoding='utf-8')


def _require(text: str, needle: str, label: str, errors: list[str]) -> None:
    if needle not in text:
        errors.append(f'{label} must include `{needle}`.')


def validate_decision(paths: DecisionPaths = DecisionPaths()) -> list[str]:
    errors: list[str] = []
    decision = _read(paths.decision_doc, errors)
    env_example = _read(paths.env_example, errors)
    production_server = _read(paths.production_server_script, errors)
    production_readiness = _read(paths.production_readiness_doc, errors)
    beta_runbook = _read(paths.beta_runbook, errors)

    _require(decision, 'Decision: single-worker hosted closed beta.', str(paths.decision_doc), errors)
    _require(decision, 'AIDM_SOCKETIO_WORKER_MODEL=single', str(paths.decision_doc), errors)
    _require(decision, 'AIDM_SOCKETIO_ASYNC_MODE=eventlet', str(paths.decision_doc), errors)
    _require(decision, 'WEB_CONCURRENCY=1', str(paths.decision_doc), errors)
    _require(decision, 'scripts/run_production_server.sh --print', str(paths.decision_doc), errors)
    _require(decision, '--socketio-staging-proof', str(paths.decision_doc), errors)
    _require(decision, 'AIDM_SOCKETIO_WORKER_MODEL=sticky', str(paths.decision_doc), errors)
    _require(decision, 'AIDM_SOCKETIO_WORKER_MODEL=message_queue', str(paths.decision_doc), errors)

    _require(env_example, 'AIDM_SOCKETIO_WORKER_MODEL=single', str(paths.env_example), errors)
    _require(env_example, 'AIDM_SOCKETIO_ASYNC_MODE=eventlet', str(paths.env_example), errors)
    _require(env_example, 'AIDM_RATE_LIMIT_STORE=database', str(paths.env_example), errors)
    _require(env_example, 'AIDM_TURN_COORDINATOR_STORE=database', str(paths.env_example), errors)

    _require(
        production_server,
        'export AIDM_SOCKETIO_WORKER_MODEL="${AIDM_SOCKETIO_WORKER_MODEL:-single}"',
        str(paths.production_server_script),
        errors,
    )
    _require(
        production_server,
        'export AIDM_SOCKETIO_ASYNC_MODE="${AIDM_SOCKETIO_ASYNC_MODE:-eventlet}"',
        str(paths.production_server_script),
        errors,
    )
    _require(production_server, 'WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"', str(paths.production_server_script), errors)
    _require(
        production_server,
        'AIDM_SOCKETIO_WORKER_MODEL=single requires WEB_CONCURRENCY=1.',
        str(paths.production_server_script),
        errors,
    )

    for path, text in (
        (paths.production_readiness_doc, production_readiness),
        (paths.beta_runbook, beta_runbook),
    ):
        _require(text, 'AIDM_SOCKETIO_WORKER_MODEL=single', str(path), errors)
        _require(text, 'AIDM_SOCKETIO_ASYNC_MODE=eventlet', str(path), errors)
        _require(text, 'WEB_CONCURRENCY=1', str(path), errors)
        _require(text, 'scripts/run_production_server.sh', str(path), errors)

    return errors


def main() -> int:
    errors = validate_decision()
    if errors:
        print('[socketio-worker-model][error] Decision check failed:', file=sys.stderr)
        for error in errors:
            print(f'- {error}', file=sys.stderr)
        return 1
    print('[socketio-worker-model] Decision verified: single worker, eventlet, WEB_CONCURRENCY=1.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
