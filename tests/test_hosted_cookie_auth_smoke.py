from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from scripts import hosted_cookie_auth_smoke


def test_hosted_cookie_auth_smoke_uses_isolated_database_by_default(tmp_path):
    external_db_path = tmp_path / 'should-not-be-created.sqlite'
    env = {
        **os.environ,
        'AIDM_DATABASE_URI': f'sqlite:///{external_db_path}',
    }

    result = subprocess.run(
        [sys.executable, 'scripts/hosted_cookie_auth_smoke.py'],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert 'Hosted cookie auth smoke passed' in result.stdout
    assert not external_db_path.exists()


def test_hosted_cookie_auth_smoke_writes_evidence_report(tmp_path):
    evidence_path = tmp_path / 'hosted-cookie-auth-evidence.md'

    exit_code = hosted_cookie_auth_smoke.main(['--evidence-report', str(evidence_path)])

    assert exit_code == 0
    markdown = evidence_path.read_text(encoding='utf-8')
    assert '# Hosted Cookie Auth Evidence' in markdown
    assert '- Status: passed' in markdown
    assert '- Mode: isolated' in markdown
    assert 'Cookie-only login used an HttpOnly account cookie' in markdown
    assert 'Role downgrade removed admin/debug capabilities' in markdown


def test_hosted_cookie_auth_smoke_writes_json_evidence_report(tmp_path):
    evidence_path = tmp_path / 'hosted-cookie-auth-evidence.json'

    exit_code = hosted_cookie_auth_smoke.main(['--evidence-report', str(evidence_path)])

    assert exit_code == 0
    payload = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert payload['status'] == 'passed'
    assert payload['mode'] == 'isolated'
    assert payload['target_url'] == ''
    assert len(payload['checks']) >= 6


def test_hosted_cookie_auth_smoke_dispatches_live_target_mode(monkeypatch):
    captured = {}

    def fake_run_live_target_smoke(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(hosted_cookie_auth_smoke, 'run_live_target_smoke', fake_run_live_target_smoke)

    exit_code = hosted_cookie_auth_smoke.main(
        [
            '--target-url',
            'https://aidm.example.test',
            '--username',
            'tester',
            '--password',
            'secret',
            '--account-intent',
            'login',
            '--workspace-name',
            'Smoke Workspace',
            '--socketio-path',
            'custom-socket.io',
            '--timeout-seconds',
            '3',
        ]
    )

    assert exit_code == 0
    assert captured == {
        'target_url': 'https://aidm.example.test',
        'username': 'tester',
        'password': 'secret',
        'account_intent': 'login',
        'workspace_name': 'Smoke Workspace',
        'socketio_path': 'custom-socket.io',
        'timeout_seconds': 3.0,
    }


def test_hosted_cookie_auth_smoke_rejects_database_uri_with_target_url():
    with pytest.raises(SystemExit) as exc_info:
        hosted_cookie_auth_smoke.main(
            [
                '--target-url',
                'https://aidm.example.test',
                '--database-uri',
                'sqlite:///should-not-be-used.sqlite',
            ]
        )

    assert exc_info.value.code == 2
