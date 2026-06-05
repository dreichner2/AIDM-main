from __future__ import annotations

import os
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPO_ROOT / 'scripts' / 'smoke_beta_flow.py'


def test_smoke_beta_flow_defaults_to_isolated_fallback(tmp_path):
    local_db = tmp_path / 'should_not_be_created.db'
    env = os.environ.copy()
    env.update(
        {
            'PYTHONPATH': str(REPO_ROOT),
            'AIDM_DATABASE_URI': f'sqlite:///{local_db}',
            'AIDM_LLM_PROVIDER': 'deepseek',
            'AIDM_LLM_MODEL': 'deepseek-v4-pro',
            'AIDM_DEEPSEEK_API_KEY': 'should-not-be-used',
        }
    )

    result = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f'STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}'
    assert 'Smoke flow passed' in result.stdout
    assert not local_db.exists()
