from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from scripts import export_support_bundle


def test_support_bundle_url_normalizes_base_and_query():
    assert export_support_bundle.support_bundle_url(
        'https://aidm.example.test/',
        session_id=42,
        limit=10,
    ) == 'https://aidm.example.test/api/beta/support-bundle?limit=10&session_id=42'


def test_support_bundle_headers_prefer_workspace_token():
    assert export_support_bundle.support_bundle_headers(
        auth_token=' secret-token ',
        workspace_id='owner',
        workspace_token=' table-token ',
    ) == {
        'Accept': 'application/json',
        'Authorization': 'Bearer secret-token',
        'X-AIDM-Workspace-Token': 'table-token',
    }


def test_default_output_path_uses_session_scope_and_utc_timestamp():
    now = datetime(2026, 6, 19, 8, 44, 14, tzinfo=timezone.utc)

    assert export_support_bundle.default_output_path(Path('tmp/support-bundles'), session_id=7, now=now) == Path(
        'tmp/support-bundles/aidm-support-bundle-session-7-20260619T084414Z.json'
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = ''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def test_fetch_support_bundle_sends_headers_and_returns_payload(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append({'url': url, 'headers': headers, 'timeout': timeout})
        return _FakeResponse(200, {'workspace_id': 'owner', 'filters': {'session_id': 3}})

    monkeypatch.setattr('scripts.export_support_bundle.requests.get', fake_get)

    payload = export_support_bundle.fetch_support_bundle(
        'https://aidm.example.test',
        auth_token='operator-token',
        workspace_id='owner',
        session_id=3,
        limit=15,
        timeout_seconds=4,
    )

    assert payload == {'workspace_id': 'owner', 'filters': {'session_id': 3}}
    assert calls == [
        {
            'url': 'https://aidm.example.test/api/beta/support-bundle?limit=15&session_id=3',
            'headers': {
                'Accept': 'application/json',
                'Authorization': 'Bearer operator-token',
                'X-AIDM-Workspace-Id': 'owner',
            },
            'timeout': 4,
        }
    ]


def test_fetch_support_bundle_reports_json_error_payload(monkeypatch):
    def fake_get(url, headers, timeout):
        del url, headers, timeout
        return _FakeResponse(403, {'error': 'Only workspace admins can export beta support bundles.'})

    monkeypatch.setattr('scripts.export_support_bundle.requests.get', fake_get)

    try:
        export_support_bundle.fetch_support_bundle('https://aidm.example.test')
    except RuntimeError as exc:
        assert '403' in str(exc)
        assert 'Only workspace admins' in str(exc)
    else:
        raise AssertionError('Expected RuntimeError')


def test_write_support_bundle_creates_parent_and_pretty_json(tmp_path: Path):
    output_path = tmp_path / 'nested' / 'bundle.json'

    export_support_bundle.write_support_bundle({'workspace_id': 'owner'}, output_path)

    assert json.loads(output_path.read_text(encoding='utf-8')) == {'workspace_id': 'owner'}
    assert output_path.read_text(encoding='utf-8').endswith('\n')
