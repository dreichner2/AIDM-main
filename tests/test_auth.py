from __future__ import annotations

import importlib
import sys

import pytest
from flask import Flask

from aidm_server.auth import extract_socket_token
from aidm_server.database import db
from aidm_server.models import Campaign, Player, Session, World


def _build_auth_runtime(tmp_path, monkeypatch, extra_env: dict[str, str] | None = None):
    db_path = tmp_path / 'auth.db'

    monkeypatch.setenv('AIDM_DATABASE_URI', f'sqlite:///{db_path}')
    monkeypatch.setenv('AIDM_AUTO_CREATE_SCHEMA', 'true')
    monkeypatch.setenv('AIDM_AUTH_REQUIRED', 'true')
    monkeypatch.setenv('AIDM_API_AUTH_TOKENS', 'token-123')
    monkeypatch.setenv('AIDM_ENV', 'test')
    monkeypatch.setenv('AIDM_DEBUG', 'false')
    monkeypatch.setenv('AIDM_SOCKETIO_ASYNC_MODE', 'threading')
    monkeypatch.setenv('AIDM_TELEMETRY_ENABLED', 'false')
    monkeypatch.setenv('AIDM_RATE_LIMIT_MAX_API_REQUESTS', '1000')
    monkeypatch.setenv('AIDM_RATE_LIMIT_MAX_SOCKET_MESSAGES', '1000')
    if extra_env:
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)

    import aidm_server.main as main_module
    main_module = importlib.reload(main_module)

    import aidm_server.blueprints.socketio_events as socketio_events_module
    socketio_events_module = importlib.reload(socketio_events_module)

    socketio_events_module.active_players.clear()
    socketio_events_module.socketio_connections.clear()

    app = main_module.create_app()
    socketio = main_module.create_socketio(app)
    socketio_events_module.register_socketio_events(socketio)

    with app.app_context():
        db.create_all()

    return app, socketio


def test_rest_auth_required(tmp_path, monkeypatch):
    app, _socketio = _build_auth_runtime(tmp_path, monkeypatch)
    client = app.test_client()

    health_response = client.get('/api/health')
    assert health_response.status_code == 200

    unauthorized = client.post('/api/worlds', json={'name': 'NoAuth'})
    assert unauthorized.status_code == 401

    authorized = client.post(
        '/api/worlds',
        json={'name': 'Authorized World', 'description': 'auth ok'},
        headers={'Authorization': 'Bearer token-123'},
    )
    assert authorized.status_code == 201


def test_auth_required_for_mutating_api_endpoints_and_tts(tmp_path, monkeypatch):
    app, _socketio = _build_auth_runtime(tmp_path, monkeypatch)
    client = app.test_client()

    with app.app_context():
        world = World(name='Auth World', description='auth coverage')
        db.session.add(world)
        db.session.flush()
        campaign = Campaign(title='Auth Campaign', world_id=world.world_id)
        db.session.add(campaign)
        db.session.flush()
        player = Player(campaign_id=campaign.campaign_id, name='Alice', character_name='Seraphina')
        db.session.add(player)
        db.session.flush()
        session = Session(campaign_id=campaign.campaign_id)
        db.session.add(session)
        db.session.commit()

        ids = {
            'world_id': world.world_id,
            'campaign_id': campaign.campaign_id,
            'player_id': player.player_id,
            'session_id': session.session_id,
        }

    mutating_requests = [
        ('post', '/api/campaigns', {'title': 'Blocked Campaign', 'world_id': ids['world_id']}),
        ('post', '/api/sessions/start', {'campaign_id': ids['campaign_id']}),
        ('post', '/api/maps', {'title': 'Blocked Map', 'campaign_id': ids['campaign_id']}),
        ('post', '/api/segments', {'campaign_id': ids['campaign_id'], 'title': 'Blocked Segment'}),
        (
            'post',
            f"/api/players/campaigns/{ids['campaign_id']}/players",
            {'name': 'Bob', 'character_name': 'Borin'},
        ),
        ('patch', f"/api/players/{ids['player_id']}", {'level': 4}),
        ('patch', f"/api/sessions/{ids['session_id']}", {'name': 'Blocked Session Rename'}),
        ('post', '/api/tts/speak', {'text': 'The torches flicker.'}),
    ]

    for method, path, payload in mutating_requests:
        response = getattr(client, method)(path, json=payload)
        assert response.status_code == 401, path
        assert response.get_json()['error_code'] == 'unauthorized'


def test_socket_auth_required(tmp_path, monkeypatch):
    app, socketio = _build_auth_runtime(tmp_path, monkeypatch)

    no_auth_client = socketio.test_client(app, flask_test_client=app.test_client())
    assert not no_auth_client.is_connected()

    query_auth_client = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        query_string='token=token-123',
    )
    assert not query_auth_client.is_connected()

    auth_client = socketio.test_client(
        app,
        flask_test_client=app.test_client(),
        auth={'token': 'token-123'},
    )
    assert auth_client.is_connected()

    import aidm_server.blueprints.socketio_events as socketio_events_module

    assert socketio_events_module.socketio_connections
    assert all('token' not in connection for connection in socketio_events_module.socketio_connections.values())
    auth_client.disconnect()


def test_socket_token_extraction_ignores_query_and_event_payloads(tmp_path, monkeypatch):
    app, _socketio = _build_auth_runtime(tmp_path, monkeypatch)

    with app.test_request_context('/socket.io/?token=token-123'):
        assert extract_socket_token(data_payload={'token': 'token-123'}) is None

    with app.test_request_context('/socket.io/', headers={'Authorization': 'Bearer token-123'}):
        assert extract_socket_token(data_payload={'token': 'ignored'}) == 'token-123'

    with app.test_request_context('/socket.io/'):
        assert extract_socket_token(auth_payload={'token': 'token-123'}) == 'token-123'


def test_admin_requires_auth_when_enabled(tmp_path, monkeypatch):
    app, _socketio = _build_auth_runtime(
        tmp_path,
        monkeypatch,
        extra_env={'AIDM_ADMIN_ENABLED': 'true'},
    )
    client = app.test_client()

    unauthorized = client.get('/admin/')
    assert unauthorized.status_code == 401

    query_token = client.get('/admin/?token=token-123')
    assert query_token.status_code == 401

    authorized = client.get('/admin/', headers={'Authorization': 'Bearer token-123'})
    assert authorized.status_code == 200


def test_admin_rejects_cookie_signed_with_old_default_secret(tmp_path, monkeypatch):
    app, _socketio = _build_auth_runtime(
        tmp_path,
        monkeypatch,
        extra_env={'AIDM_ADMIN_ENABLED': 'true'},
    )
    client = app.test_client()

    forged_app = Flask(__name__)
    forged_app.secret_key = 'dev-secret-change-me'
    serializer = forged_app.session_interface.get_signing_serializer(forged_app)
    assert serializer is not None
    forged_cookie = serializer.dumps({'aidm_admin_authorized': True})

    client.set_cookie(app.config.get('SESSION_COOKIE_NAME', 'session'), forged_cookie)
    response = client.get('/admin/')

    assert response.status_code == 401


def test_production_requires_explicit_secret_key(tmp_path, monkeypatch):
    db_path = tmp_path / 'prod_auth.db'
    monkeypatch.setenv('AIDM_DATABASE_URI', f'sqlite:///{db_path}')
    monkeypatch.setenv('AIDM_AUTO_CREATE_SCHEMA', 'false')
    monkeypatch.setenv('AIDM_ENV', 'production')
    monkeypatch.setenv('AIDM_DEBUG', 'false')
    monkeypatch.setenv('AIDM_AUTH_REQUIRED', 'true')
    monkeypatch.setenv('AIDM_API_AUTH_TOKENS', 'token-123')
    monkeypatch.setenv('AIDM_SOCKETIO_ASYNC_MODE', 'threading')
    monkeypatch.setenv('AIDM_TELEMETRY_ENABLED', 'false')
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)

    with pytest.raises(ValueError, match='FLASK_SECRET_KEY'):
        if 'aidm_server.main' in sys.modules:
            main_module = importlib.reload(sys.modules['aidm_server.main'])
        else:
            main_module = importlib.import_module('aidm_server.main')
        main_module.create_app()


def test_api_rate_limit_ignores_spoofed_forwarded_for(tmp_path, monkeypatch):
    app, _socketio = _build_auth_runtime(
        tmp_path,
        monkeypatch,
        extra_env={'AIDM_RATE_LIMIT_MAX_API_REQUESTS': '1'},
    )
    client = app.test_client()
    headers = {'Authorization': 'Bearer token-123'}

    first = client.get('/api/metrics', headers={**headers, 'X-Forwarded-For': '1.1.1.1'})
    second = client.get('/api/metrics', headers={**headers, 'X-Forwarded-For': '2.2.2.2'})

    assert first.status_code == 200
    assert second.status_code == 429
