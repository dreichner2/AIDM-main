from __future__ import annotations

import os
import subprocess


def test_production_server_command_prints_single_worker_eventlet_command():
    env = {
        **os.environ,
        'PORT': '6060',
        'GUNICORN_BIN': 'gunicorn-test',
        'AIDM_GUNICORN_TIMEOUT': '90',
    }

    result = subprocess.run(
        ['bash', 'scripts/run_production_server.sh', '--print'],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    command = result.stdout.strip()
    assert command.startswith('gunicorn-test ')
    assert '--worker-class eventlet' in command
    assert '--workers 1' in command
    assert '--bind 0.0.0.0:6060' in command
    assert '--timeout 90' in command
    assert command.endswith('aidm_server.wsgi:app')


def test_production_server_command_rejects_multi_worker_single_model():
    env = {
        **os.environ,
        'AIDM_SOCKETIO_WORKER_MODEL': 'single',
        'WEB_CONCURRENCY': '2',
    }

    result = subprocess.run(
        ['bash', 'scripts/run_production_server.sh', '--print'],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert 'AIDM_SOCKETIO_WORKER_MODEL=single requires WEB_CONCURRENCY=1.' in result.stderr
