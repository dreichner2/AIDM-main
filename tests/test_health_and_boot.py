from __future__ import annotations

import importlib

from aidm_server.database import _resolve_sqlite_uri
from aidm_server.database import ensure_schema


def test_health_endpoint_available_without_llm_key(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'ok'
    assert 'auth_required' in payload


def test_non_ai_crud_works_without_llm_key(client):
    response = client.post('/api/worlds', json={'name': 'Faerun', 'description': 'High fantasy'})
    assert response.status_code == 201
    payload = response.get_json()
    assert payload['world_id'] > 0


def test_worlds_can_be_listed_for_campaign_creation_lookup(client):
    first = client.post('/api/worlds', json={'name': 'First World', 'description': 'Older'})
    second = client.post('/api/worlds', json={'name': 'Second World', 'description': 'Newer'})
    assert first.status_code == 201
    assert second.status_code == 201

    response = client.get('/api/worlds')

    assert response.status_code == 200
    payload = response.get_json()
    names = [world['name'] for world in payload]
    assert 'First World' in names
    assert 'Second World' in names
    assert {'world_id', 'name', 'description', 'created_at'} <= set(payload[0])


def test_http_response_includes_request_correlation_id(client):
    response = client.get('/api/health', headers={'X-Request-ID': 'test-correlation-id'})
    assert response.status_code == 200
    assert response.headers.get('X-Request-ID') == 'test-correlation-id'


def test_root_reports_backend_metadata(client):
    response = client.get('/')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {
        'service': 'aidm_backend',
        'status': 'ok',
        'frontend': 'React app served separately from aidm_frontend',
    }


def test_legacy_codex_frontend_route_is_removed(client):
    response = client.get('/codex')

    assert response.status_code == 404


def test_admin_ui_is_not_registered_when_disabled(client):
    response = client.get('/admin/')

    assert response.status_code == 404


def test_admin_ui_can_be_enabled_for_local_development(tmp_path, monkeypatch):
    db_path = tmp_path / 'admin_enabled.db'
    monkeypatch.setenv('AIDM_DATABASE_URI', f'sqlite:///{db_path}')
    monkeypatch.setenv('AIDM_AUTO_CREATE_SCHEMA', 'true')
    monkeypatch.setenv('AIDM_ENV', 'local')
    monkeypatch.setenv('AIDM_ADMIN_ENABLED', 'true')
    monkeypatch.setenv('AIDM_DEBUG', 'false')
    monkeypatch.setenv('AIDM_CORS_ALLOWLIST', 'http://localhost')
    monkeypatch.setenv('AIDM_SOCKET_CORS_ALLOWLIST', 'http://localhost')
    monkeypatch.setenv('AIDM_TELEMETRY_ENABLED', 'false')

    import aidm_server.main as main_module

    main_module = importlib.reload(main_module)
    app = main_module.create_app()
    ensure_schema(app)

    response = app.test_client().get('/admin/')

    assert response.status_code == 200


def test_llm_config_update_requires_json_body(client):
    response = client.post('/api/llm/config', data='not-json', content_type='text/plain')

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'


def test_in_memory_sqlite_uri_is_not_rewritten():
    assert _resolve_sqlite_uri('sqlite:///:memory:', '/tmp/app-root') == 'sqlite:///:memory:'


def test_main_module_stays_factory_only():
    import aidm_server.main as main_module

    main_module = importlib.reload(main_module)

    assert not hasattr(main_module, 'app')
    assert not hasattr(main_module, 'socketio')
