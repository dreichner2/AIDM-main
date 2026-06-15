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
            'PYTHON_DOTENV_DISABLED': '1',
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


def test_check_local_health_sends_auth_header_when_token_is_configured(tmp_path):
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
            'AIDM_AUTH_TOKEN': 'test-token',
            'AIDM_BACKEND_URL': 'http://backend.example.test',
            'AIDM_FRONTEND_URL': 'http://frontend.example.test',
            'AIDM_CURL_LOG': str(curl_log),
            'AIDM_PYTHON': sys.executable,
            'PYTHON_DOTENV_DISABLED': '1',
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
    assert curl_log.read_text(encoding='utf-8').splitlines() == [
        '--fail --silent --show-error -H Authorization: Bearer test-token http://backend.example.test/api/health',
        '--fail --silent --show-error -H Authorization: Bearer test-token http://backend.example.test/api/llm/config',
        '--fail --silent --show-error -H Authorization: Bearer test-token http://backend.example.test/api/tts/config',
        '--fail --silent --show-error -H Authorization: Bearer test-token http://frontend.example.test',
    ]


def test_check_local_health_falls_back_to_unified_frontend(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    curl_log = tmp_path / 'curl.log'
    fake_curl = bin_dir / 'curl'
    fake_curl.write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "$*" >> "${AIDM_CURL_LOG}"\n'
        'if [[ "${*: -1}" == "http://frontend.example.test" ]]; then exit 22; fi\n'
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
            'PYTHON_DOTENV_DISABLED': '1',
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
    assert 'Frontend fallback: http://backend.example.test/' in result.stdout
    assert curl_log.read_text(encoding='utf-8').splitlines()[-2:] == [
        '--fail --silent --show-error http://frontend.example.test',
        '--fail --silent --show-error http://backend.example.test/',
    ]
