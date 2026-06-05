from __future__ import annotations

import os
import pathlib
import subprocess


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PRUNE_SCRIPT = REPO_ROOT / 'scripts' / 'prune_launcher_logs.sh'


def test_prune_launcher_logs_rotates_large_logs(tmp_path):
    log_dir = tmp_path / 'launcher_logs'
    log_dir.mkdir()
    log_file = log_dir / 'launcher.log'
    log_file.write_text('x' * 24, encoding='utf-8')

    env = os.environ.copy()
    env['AIDM_LAUNCHER_LOG_MAX_BYTES'] = '10'
    env['AIDM_LAUNCHER_LOG_KEEP'] = '2'

    result = subprocess.run(
        ['bash', str(PRUNE_SCRIPT), str(log_dir)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert log_file.read_text(encoding='utf-8') == ''
    assert (log_dir / 'launcher.log.1').read_text(encoding='utf-8') == 'x' * 24


def test_prune_launcher_logs_rejects_invalid_budget(tmp_path):
    env = os.environ.copy()
    env['AIDM_LAUNCHER_LOG_MAX_BYTES'] = 'nope'

    result = subprocess.run(
        ['bash', str(PRUNE_SCRIPT), str(tmp_path)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert 'AIDM_LAUNCHER_LOG_MAX_BYTES' in result.stderr
