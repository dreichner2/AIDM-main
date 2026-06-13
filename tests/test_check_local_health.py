from __future__ import annotations

import os
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
HEALTH_SCRIPT = REPO_ROOT / 'scripts' / 'check_local_health.sh'


def test_check_local_health_runs_from_non_repo_cwd_with_python_override(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    curl_log = tmp_path / 'curl.log'
    fake_curl = bin_dir / 'curl'
    fake_curl.write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "$*" >> "${AIDM_CURL_LOG}"\n'
        'exit 0\n',
        encoding='utf-8',
    )
    fake_curl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            'AIDM_BACKEND_URL': 'http://backend.example.test',
            'AIDM_FRONTEND_URL': 'http://frontend.example.test',
            'AIDM_CURL_LOG': str(curl_log),
            'AIDM_PYTHON': sys.executable,
            'PATH': f'{bin_dir}{os.pathsep}{env["PATH"]}',
        }
    )

    result = subprocess.run(
        ['bash', str(HEALTH_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert 'Configured local database URI:' in result.stdout
    assert curl_log.read_text(encoding='utf-8').splitlines() == [
        '--fail --silent --show-error http://backend.example.test/api/health',
        '--fail --silent --show-error http://backend.example.test/api/llm/config',
        '--fail --silent --show-error http://backend.example.test/api/tts/config',
        '--fail --silent --show-error http://frontend.example.test',
    ]
