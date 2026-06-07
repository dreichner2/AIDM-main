from __future__ import annotations

import json

from aidm_server.database import db
from aidm_server.models import (
    Campaign,
    CampaignSegment,
    DmTurn,
    Player,
    PlayerAction,
    Session,
    SessionState,
    StoryEntity,
    StoryThread,
    TurnEvent,
    TurnCanonUpdate,
    World,
    safe_json_dumps,
    safe_json_loads,
)
from tests.helpers import seed_segment, seed_world_campaign_player_session


def _event_payload(received, name):
    for event in received:
        if event['name'] == name:
            return event['args'][0] if event['args'] else {}
    return None


def test_send_message_persists_turn_and_emits_metadata(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']
    turn_engine_module = app_runtime['modules']['turn_engine']
    telemetry_events = []

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The corridor hums with ancient magic.'

    def fake_telemetry_event(event_name, payload=None, severity='info'):
        telemetry_events.append({'event_name': event_name, 'payload': payload or {}, 'severity': severity})

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)
    monkeypatch.setattr(turn_engine_module, 'telemetry_event', fake_telemetry_event)

    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        player = db.session.get(Player, ids['player_id'])
        assert player is not None
        player.inventory = None
        StoryEntity.query.filter_by(campaign_id=ids['campaign_id'], entity_type='item').delete()
        db.session.commit()

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin sentry.',
        },
    )
    received = client.get_received()

    start_payload = _event_payload(received, 'dm_response_start')
    chunk_payload = _event_payload(received, 'dm_chunk')
    end_payload = _event_payload(received, 'dm_response_end')

    assert start_payload is not None
    assert chunk_payload is not None
    assert end_payload is not None

    assert start_payload['turn_id'] > 0
    assert start_payload['requires_roll'] is True
    assert 'rules_hint' in start_payload
    assert start_payload['context_version'] == 'v2'
    assert start_payload['rules_hint']['confidence'] > 0.0
    assert 'outcome_deferred' in start_payload['rules_hint']
    stream_started = next(event for event in telemetry_events if event['event_name'] == 'socket.dm_stream_started')
    assert stream_started['payload']['turn_id'] == start_payload['turn_id']
    assert stream_started['payload']['provider'] == app.config['AIDM_LLM_PROVIDER']
    assert stream_started['payload']['model'] == app.config['AIDM_LLM_MODEL']

    with app.app_context():
        turn = DmTurn.query.order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        assert turn.player_input == 'I attack the goblin sentry.'
        assert turn.requires_roll is True
        assert turn.confidence is not None
        assert turn.outcome_status in {'deferred', 'resolved'}
        assert 'corridor hums' in (turn.dm_output or '').lower()

        state = SessionState.query.filter_by(session_id=ids['session_id']).first()
        assert state is not None
        assert state.rolling_summary

        event_types = [
            event.event_type
            for event in TurnEvent.query.filter_by(session_id=ids['session_id']).order_by(TurnEvent.event_id.asc()).all()
        ]
        assert 'player_message' in event_types
        assert 'dm_response' in event_types
        assert 'canon_applied' in event_types

    metrics = app.test_client().get('/api/metrics').get_json()
    phase_keys = [
        key
        for key in metrics['timings']
        if key.startswith('socket.turn_phase_latency_ms|')
    ]
    for phase in {
        'context_build',
        'provider_time_to_first_token',
        'provider_total',
        'dm_response_emit',
        'db_save',
        'canon_extraction',
        'canon_validation',
        'projection_refresh',
    }:
        assert any(f'phase={phase}' in key for key in phase_keys)


def test_send_message_persists_typed_action_intent_and_status_events(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        del user_input, context, speaking_player, rules_hint
        yield 'The roll carries cleanly into the scene.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I roll a d20+2 for the ward: 18 = 20',
            'action_intent': {
                'kind': 'roll',
                'source': 'dice_roller',
                'text': 'I roll a d20+2 for the ward: 18 = 20',
                'client_message_id': 'typed-roll-1',
                'roll': {
                    'die': 'd20',
                    'mode': 'advantage',
                    'modifier': 2,
                    'rolls': [7, 18],
                    'kept': 18,
                    'total': 20,
                    'result_visibility': 'hidden_until_landed',
                    'reason': 'the ward',
                },
            },
        },
    )
    received = client.get_received()

    statuses = [event['args'][0]['status'] for event in received if event['name'] == 'turn_status']
    assert {'received', 'narrating', 'response_complete', 'saving', 'saved', 'canon_pending', 'canon_applied'}.issubset(set(statuses))
    start_payload = _event_payload(received, 'dm_response_start')
    assert start_payload['rules_hint']['roll_value'] == 20

    with app.app_context():
        turn = DmTurn.query.order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        metadata = safe_json_loads(turn.metadata_json, {})
        assert metadata['client_message_id'] == 'typed-roll-1'
        assert metadata['action_intent']['roll']['total'] == 20
        player_event = TurnEvent.query.filter_by(event_type='player_message').order_by(TurnEvent.event_id.desc()).first()
        assert player_event is not None
        payload = safe_json_loads(player_event.payload_json, {})
        assert payload['metadata']['action_intent']['kind'] == 'roll'


def test_send_message_rejects_invalid_action_intent(app, socketio):
    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'player_id': ids['player_id'],
            'message': 'Bad roll payload',
            'action_intent': {
                'kind': 'roll',
                'roll': {
                    'die': 'd20',
                    'mode': 'normal',
                    'modifier': 1,
                    'rolls': [8],
                    'kept': 8,
                    'total': 99,
                },
            },
        },
    )

    error_payload = _event_payload(client.get_received(), 'error')
    assert error_payload['error_code'] == 'validation_error'
    assert 'roll.total' in error_payload['error']


def test_admin_message_requires_configured_admin_passcode(app, socketio):
    app.config['AIDM_ADMIN_PASSCODE'] = None
    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'player_id': ids['player_id'],
            'message': '[ADMIN] Open the sealed vault.',
            'action_intent': {
                'kind': 'admin',
                'source': 'composer',
                'text': 'Open the sealed vault.',
            },
            'admin_passcode': 'letmein',
        },
    )

    error_payload = _event_payload(client.get_received(), 'error')
    assert error_payload['error_code'] == 'admin_not_configured'
    with app.app_context():
        assert DmTurn.query.filter_by(session_id=ids['session_id']).count() == 0


def test_admin_message_rejects_invalid_passcode_before_creating_turn(app, socketio):
    app.config['AIDM_ADMIN_PASSCODE'] = 'letmein'
    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'player_id': ids['player_id'],
            'message': '[ADMIN] Open the sealed vault.',
            'action_intent': {
                'kind': 'admin',
                'source': 'composer',
                'text': 'Open the sealed vault.',
            },
            'admin_passcode': 'wrong',
        },
    )

    error_payload = _event_payload(client.get_received(), 'error')
    assert error_payload['error_code'] == 'admin_unauthorized'
    with app.app_context():
        assert DmTurn.query.filter_by(session_id=ids['session_id']).count() == 0


def test_admin_message_with_passcode_forces_admin_override_without_storing_passcode(
    app,
    socketio,
    app_runtime,
    monkeypatch,
):
    app.config['AIDM_ADMIN_PASSCODE'] = 'letmein'
    socketio_module = app_runtime['modules']['socketio_events']
    captured = {}

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        del context, speaking_player
        captured['user_input'] = user_input
        captured['rules_hint'] = rules_hint
        yield 'The vault door opens exactly as directed.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': '[ADMIN] Open the sealed vault and place Ember beside it.',
            'action_intent': {
                'kind': 'admin',
                'source': 'composer',
                'text': 'Open the sealed vault and place Ember beside it.',
                'client_message_id': 'admin-override-1',
            },
            'admin_passcode': 'letmein',
        },
    )
    received = client.get_received()

    assert _event_payload(received, 'error') is None
    start_payload = _event_payload(received, 'dm_response_start')
    assert start_payload is not None
    assert start_payload['requires_roll'] is False
    assert start_payload['rules_hint']['reason'] == 'Authenticated admin override'
    assert captured['rules_hint']['requires_roll'] is False
    assert captured['rules_hint']['reason'] == 'Authenticated admin override'
    assert captured['user_input'].startswith('ADMIN OVERRIDE (authenticated):')
    assert 'Open the sealed vault and place Ember beside it.' in captured['user_input']
    assert '[ADMIN]' not in captured['user_input']

    with app.app_context():
        turn = DmTurn.query.filter_by(session_id=ids['session_id']).order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        assert turn.player_input == '[ADMIN] Open the sealed vault and place Ember beside it.'
        assert turn.requires_roll is False
        assert turn.outcome_status == 'resolved'
        metadata = safe_json_loads(turn.metadata_json, {})
        assert metadata['action_intent']['kind'] == 'admin'
        assert metadata['action_intent']['client_message_id'] == 'admin-override-1'
        assert 'admin_passcode' not in metadata
        assert 'admin_passcode' not in metadata['action_intent']


def test_player_interaction_intent_clarifies_target_for_dm(
    app,
    socketio,
    app_runtime,
    monkeypatch,
):
    socketio_module = app_runtime['modules']['socketio_events']
    captured = {}

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        del context, speaking_player, rules_hint
        captured['user_input'] = user_input
        yield 'Borin hears Seraphina clearly.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    with app.app_context():
        target_player = Player(
            campaign_id=ids['campaign_id'],
            name='Maya',
            character_name='Borin',
            race='Dwarf',
            class_='Fighter',
            level=2,
        )
        db.session.add(target_player)
        db.session.commit()
        target_player_id = target_player.player_id

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'Seraphina says to Borin: hold the bridge.',
            'action_intent': {
                'kind': 'interact',
                'source': 'composer',
                'text': 'Seraphina says to Borin: hold the bridge.',
                'client_message_id': 'interact-1',
                'interaction': {'type': 'speak_to', 'label': 'Speak to'},
                'target': {
                    'player_id': target_player_id,
                    'character_name': 'Stale Name',
                    'player_name': 'Stale Player',
                },
            },
        },
    )
    received = client.get_received()

    assert _event_payload(received, 'error') is None
    assert captured['user_input'].startswith('PLAYER-TO-PLAYER INTERACTION:')
    assert 'Acting character: Seraphina' in captured['user_input']
    assert 'Target character: Borin' in captured['user_input']
    assert 'Target player profile: Maya' in captured['user_input']
    assert 'even if they have not spoken in the current chat log yet' in captured['user_input']

    with app.app_context():
        turn = DmTurn.query.filter_by(session_id=ids['session_id']).order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        metadata = safe_json_loads(turn.metadata_json, {})
        assert metadata['action_intent']['kind'] == 'interact'
        assert metadata['action_intent']['target'] == {
            'player_id': target_player_id,
            'character_name': 'Borin',
            'player_name': 'Maya',
        }


def test_send_message_ignores_duplicate_client_message_id(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']
    calls = {'count': 0}

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        del user_input, context, speaking_player, rules_hint
        calls['count'] += 1
        yield 'Only once.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    payload = {
        'session_id': ids['session_id'],
        'campaign_id': ids['campaign_id'],
        'player_id': ids['player_id'],
        'message': 'I proceed.',
        'client_message_id': 'duplicate-1',
    }
    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit('send_message', payload)
    client.get_received()
    client.emit('send_message', payload)
    received = client.get_received()

    assert _event_payload(received, 'turn_duplicate') is not None
    assert calls['count'] == 1
    with app.app_context():
        assert DmTurn.query.count() == 1


def test_dm_response_is_saved_when_canon_extraction_fails(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']
    import aidm_server.canon_jobs as canon_jobs_module

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        del user_input, context, speaking_player, rules_hint
        yield 'Saved before canon.'

    def fail_extract(*args, **kwargs):
        del args, kwargs
        raise RuntimeError('canon down')

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)
    monkeypatch.setattr(canon_jobs_module, 'extract_canon_patch', fail_extract)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'player_id': ids['player_id'],
            'message': 'I inspect the failed canon path.',
        },
    )
    received = client.get_received()
    statuses = [event['args'][0]['status'] for event in received if event['name'] == 'turn_status']

    assert 'saved' in statuses
    assert 'failed' in statuses
    with app.app_context():
        turn = DmTurn.query.order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        assert turn.dm_output.startswith('Saved before canon.')
        assert turn.status == 'completed'
        metadata = safe_json_loads(turn.metadata_json, {})
        assert metadata['canon_status'] == 'failed'


def test_send_message_strips_reasoning_tags_from_stream_and_storage(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        del user_input, context, speaking_player, rules_hint
        yield '<thought>hidden plan'
        yield ' still hidden</thought>The corridor is clear.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'player_id': ids['player_id'],
            'message': 'I listen at the corridor.',
        },
    )
    received = client.get_received()
    chunks = [event['args'][0]['chunk'] for event in received if event['name'] == 'dm_chunk']

    assert ''.join(chunks) == 'The corridor is clear.'
    assert all('hidden' not in chunk for chunk in chunks)

    with app.app_context():
        turn = DmTurn.query.order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        assert turn.dm_output == 'The corridor is clear.'


def test_segment_trigger_activates_and_emits_event(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'A hidden mechanism clicks into place.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    seed_segment(
        app,
        campaign_id=ids['campaign_id'],
        trigger_condition='{"type":"keywords","keywords":["altar"],"match":"any"}',
    )

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I inspect the altar and press the rune.',
        },
    )
    received = client.get_received()

    segment_payload = _event_payload(received, 'segment_triggered')
    assert segment_payload is not None
    assert segment_payload['title'] == 'Hidden Chamber Unlocked'

    with app.app_context():
        segment = CampaignSegment.query.filter_by(campaign_id=ids['campaign_id']).first()
        assert segment is not None
        assert segment.is_triggered is True


def test_state_segment_triggers_on_same_turn_after_projection_updates(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'You enter the chapel and the soot-stained bells settle around you.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    seed_segment(
        app,
        campaign_id=ids['campaign_id'],
        trigger_condition='{"type":"state","location_contains":"chapel"}',
    )

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I enter the chapel.',
        },
    )
    received = client.get_received()

    segment_payload = _event_payload(received, 'segment_triggered')
    assert segment_payload is not None
    assert segment_payload['title'] == 'Hidden Chamber Unlocked'

    with app.app_context():
        segment = CampaignSegment.query.filter_by(campaign_id=ids['campaign_id']).first()
        assert segment is not None
        assert segment.is_triggered is True


def test_manual_segment_override_is_rejected(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'Manual trigger acknowledged.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    segment_id = seed_segment(
        app,
        campaign_id=ids['campaign_id'],
        trigger_condition='{"type":"manual"}',
    )

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I proceed cautiously.',
            'manual_trigger_segment_ids': [segment_id],
        },
    )
    received = client.get_received()

    error_payload = _event_payload(received, 'error')
    assert error_payload is not None
    assert error_payload['error_code'] == 'manual_segment_override_disabled'
    assert _event_payload(received, 'segment_triggered') is None

    with app.app_context():
        segment = db.session.get(CampaignSegment, segment_id)
        assert segment is not None
        assert segment.is_triggered is False


def test_send_message_rejects_player_identity_mismatch_for_joined_socket(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The scene advances.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        other_player = Player(
            campaign_id=ids['campaign_id'],
            name='Borin',
            character_name='Borin',
            race='Dwarf',
            class_='Cleric',
            level=2,
        )
        db.session.add(other_player)
        db.session.commit()
        other_player_id = other_player.player_id

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': other_player_id,
            'message': 'I should not be able to speak as Borin.',
        },
    )
    received = client.get_received()
    error_payload = _event_payload(received, 'error')

    assert error_payload is not None
    assert error_payload['error_code'] == 'player_identity_mismatch'
    assert _event_payload(received, 'dm_response_start') is None

    with app.app_context():
        assert DmTurn.query.filter_by(session_id=ids['session_id']).count() == 0


def test_invalid_player_campaign_pairing_rejected_without_writes(app, socketio):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        world_2 = World(name='World 2', description='second world')
        db.session.add(world_2)
        db.session.flush()

        campaign_2 = Campaign(title='Campaign 2', description='second', world_id=world_2.world_id)
        db.session.add(campaign_2)
        db.session.flush()

        outsider_player = Player(
            campaign_id=campaign_2.campaign_id,
            name='Bob',
            character_name='Thorne',
            race='Human',
            class_='Fighter',
            level=2,
        )
        db.session.add(outsider_player)
        db.session.commit()

        outsider_player_id = outsider_player.player_id

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': outsider_player_id,
            'message': 'I should not be allowed in this campaign.',
        },
    )
    received = client.get_received()

    error_payload = _event_payload(received, 'error')
    assert error_payload is not None
    assert error_payload['error_code'] == 'player_identity_mismatch'

    with app.app_context():
        outsider_actions = PlayerAction.query.filter_by(player_id=outsider_player_id).all()
        assert outsider_actions == []


def test_session_state_progresses_location_and_quest(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'You sprint into the rooftop gutters as the alarm is active across the district.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    seed_segment(
        app,
        campaign_id=ids['campaign_id'],
        trigger_condition='{"type":"keywords","keywords":["sigil"],"match":"any"}',
    )

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I inspect the sigil, then sprint for the rooftop gutters.',
        },
    )
    client.get_received()

    with app.app_context():
        state = SessionState.query.filter_by(session_id=ids['session_id']).first()
        assert state is not None
        assert state.current_location == 'rooftop gutters'
        assert 'Hidden Chamber Unlocked' in (state.current_quest or '')


def test_turn_creates_emergent_memory_records(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'Liora leads you into the rooftop gutters above the chapel as the bell tower burns.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    seed_segment(
        app,
        campaign_id=ids['campaign_id'],
        trigger_condition='{"type":"keywords","keywords":["chapel"],"match":"any"}',
    )

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I rush toward the chapel and follow Liora upward.',
        },
    )
    client.get_received()

    with app.app_context():
        entities = StoryEntity.query.filter_by(campaign_id=ids['campaign_id']).all()
        entity_names = {(entity.entity_type, entity.name.lower()) for entity in entities}
        assert ('location', 'rooftop gutters') in entity_names
        assert ('npc', 'liora') in entity_names

        threads = StoryThread.query.filter_by(campaign_id=ids['campaign_id']).all()
        assert any(thread.title == 'Hidden Chamber Unlocked' and thread.source == 'segment' for thread in threads)

        updates = TurnCanonUpdate.query.all()
        assert len(updates) == 1
        assert updates[0].status == 'applied'


def test_explicit_inventory_gain_updates_player_inventory(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'You take the silver key from the altar and tuck it into your cloak.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I grab the silver key.',
        },
    )
    client.get_received()

    with app.app_context():
        player = db.session.get(Player, ids['player_id'])
        assert player is not None
        inventory = safe_json_loads(player.inventory, [])
        assert any(item.get('name') == 'silver key' and item.get('quantity') == 1 for item in inventory)

        item_entities = StoryEntity.query.filter_by(campaign_id=ids['campaign_id'], entity_type='item').all()
        assert any(entity.name == 'silver key' for entity in item_entities)

        update = TurnCanonUpdate.query.order_by(TurnCanonUpdate.update_id.desc()).first()
        assert update is not None
        applied = safe_json_loads(update.applied_patch_json, {})
        assert applied['inventory_changes_applied'][0]['item_name'] == 'silver key'


def test_canon_job_failure_keeps_dm_response_saved(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']
    import aidm_server.canon_jobs as canon_jobs_module

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The corridor hums with ancient magic.'

    def fail_apply_canon_patch(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)
    monkeypatch.setattr(canon_jobs_module, 'apply_canon_patch', fail_apply_canon_patch)

    ids = seed_world_campaign_player_session(app)

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I inspect the corridor.',
        },
    )
    received = client.get_received()
    statuses = [event['args'][0]['status'] for event in received if event['name'] == 'turn_status']

    assert 'failed' in statuses
    assert _event_payload(received, 'error') is None
    with app.app_context():
        turn = DmTurn.query.order_by(DmTurn.turn_id.desc()).first()
        assert turn is not None
        assert turn.status == 'completed'
        assert 'corridor hums' in (turn.dm_output or '').lower()
        metadata = safe_json_loads(turn.metadata_json, {})
        assert metadata['canon_status'] == 'failed'


def test_join_session_rejects_player_from_other_workspace(app, socketio, app_runtime):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        other_world = World(
            name='Other World',
            description='Separate test world',
            workspace_id='friend',
        )
        db.session.add(other_world)
        db.session.flush()
        other_campaign = Campaign(
            title='Other Campaign',
            world_id=other_world.world_id,
            workspace_id='friend',
        )
        db.session.add(other_campaign)
        db.session.flush()
        other_player = Player(
            workspace_id='friend',
            campaign_id=other_campaign.campaign_id,
            name='Bob',
            character_name='Bob',
        )
        db.session.add(other_player)
        db.session.commit()
        other_player_id = other_player.player_id

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': other_player_id})
    received = client.get_received()
    error_payload = _event_payload(received, 'error')

    assert error_payload is not None
    assert error_payload['error_code'] == 'invalid_player'
    assert _event_payload(received, 'player_joined') is None


def test_duplicate_player_connections_do_not_emit_player_left_until_last_disconnect(app, socketio, app_runtime):
    socketio_module = app_runtime['modules']['socketio_events']
    ids = seed_world_campaign_player_session(app)

    client_one = socketio.test_client(app, flask_test_client=app.test_client())
    client_two = socketio.test_client(app, flask_test_client=app.test_client())
    assert client_one.is_connected()
    assert client_two.is_connected()

    client_one.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client_one.get_received()
    client_two.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client_two.get_received()

    client_one.disconnect()
    received = client_two.get_received()

    assert _event_payload(received, 'player_left') is None
    assert ids['session_id'] in socketio_module.active_players
    assert ids['player_id'] in socketio_module.active_players[ids['session_id']]

    client_two.disconnect()
    assert ids['session_id'] not in socketio_module.active_players or (
        ids['player_id'] not in socketio_module.active_players.get(ids['session_id'], {})
    )


def test_other_player_is_not_blocked_by_another_players_pending_check(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The scene advances.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        other_player = Player(
            campaign_id=ids['campaign_id'],
            name='Borin',
            character_name='Borin',
            race='Dwarf',
            class_='Cleric',
            level=2,
        )
        db.session.add(other_player)
        db.session.commit()
        other_player_id = other_player.player_id

    client_one = socketio.test_client(app, flask_test_client=app.test_client())
    client_two = socketio.test_client(app, flask_test_client=app.test_client())
    assert client_one.is_connected()
    assert client_two.is_connected()

    client_one.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client_one.get_received()
    client_two.emit('join_session', {'session_id': ids['session_id'], 'player_id': other_player_id})
    client_two.get_received()

    client_one.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin.',
        },
    )
    client_one.get_received()

    client_two.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': other_player_id,
            'message': 'I wait by the doorway and watch the corridor.',
        },
    )
    events = client_two.get_received()

    assert _event_payload(events, 'error') is None
    assert _event_payload(events, 'dm_response_start') is not None

    with app.app_context():
        turns = DmTurn.query.filter_by(session_id=ids['session_id']).order_by(DmTurn.turn_id.asc()).all()
        assert len(turns) == 2
        assert turns[0].player_id == ids['player_id']
        assert turns[0].outcome_status == 'deferred'
        assert turns[1].player_id == other_player_id


def test_roll_cannot_resolve_another_players_pending_turn(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The scene advances.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        other_player = Player(
            campaign_id=ids['campaign_id'],
            name='Borin',
            character_name='Borin',
            race='Dwarf',
            class_='Cleric',
            level=2,
        )
        db.session.add(other_player)
        db.session.commit()
        other_player_id = other_player.player_id

    client_one = socketio.test_client(app, flask_test_client=app.test_client())
    client_two = socketio.test_client(app, flask_test_client=app.test_client())
    assert client_one.is_connected()
    assert client_two.is_connected()

    client_one.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client_one.get_received()
    client_two.emit('join_session', {'session_id': ids['session_id'], 'player_id': other_player_id})
    client_two.get_received()

    client_one.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin.',
        },
    )
    first_events = client_one.get_received()
    first_start = _event_payload(first_events, 'dm_response_start')
    assert first_start is not None
    pending_turn_id = first_start['turn_id']
    client_two.get_received()

    client_two.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': other_player_id,
            'message': 'I roll a d20: 18',
        },
    )
    second_events = client_two.get_received()
    error_payload = _event_payload(second_events, 'error')

    assert error_payload is not None
    assert error_payload['error_code'] == 'pending_roll_not_owned'
    assert _event_payload(second_events, 'dm_response_start') is None

    with app.app_context():
        first_turn = db.session.get(DmTurn, pending_turn_id)
        assert first_turn is not None
        assert first_turn.outcome_status == 'deferred'
        assert DmTurn.query.filter_by(session_id=ids['session_id']).count() == 1


def test_turn_uses_campaign_world_context_even_when_client_world_id_is_wrong(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']
    captured_context = {}

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        captured_context['payload'] = json.loads(context)
        yield 'The scene advances.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    with app.app_context():
        world_one = World(name='World One', description='one')
        world_two = World(name='World Two', description='two')
        db.session.add_all([world_one, world_two])
        db.session.flush()

        campaign = Campaign(title='Campaign One', world_id=world_one.world_id)
        db.session.add(campaign)
        db.session.flush()

        player = Player(campaign_id=campaign.campaign_id, name='A', character_name='Alpha')
        db.session.add(player)
        db.session.flush()

        session = Session(campaign_id=campaign.campaign_id)
        db.session.add(session)
        db.session.commit()

        ids = {
            'world_id': world_one.world_id,
            'wrong_world_id': world_two.world_id,
            'campaign_id': campaign.campaign_id,
            'player_id': player.player_id,
            'session_id': session.session_id,
        }

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['wrong_world_id'],
            'player_id': ids['player_id'],
            'message': 'I look around.',
        },
    )
    client.get_received()

    assert captured_context['payload']['world']['world_id'] == ids['world_id']
    assert captured_context['payload']['world']['name'] == 'World One'


def test_send_message_does_not_require_client_world_id(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']
    captured_context = {}

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        captured_context['payload'] = json.loads(context)
        yield 'The scene advances without client world echo.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()
    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'player_id': ids['player_id'],
            'message': 'I look around without sending a world id.',
        },
    )
    received = client.get_received()

    assert _event_payload(received, 'error') is None
    assert _event_payload(received, 'dm_response_start') is not None
    assert captured_context['payload']['world']['world_id'] == ids['world_id']


def test_roll_resolves_pending_turn_and_carries_rule_type(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The encounter advances.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin.',
        },
    )
    first_events = client.get_received()
    first_start = _event_payload(first_events, 'dm_response_start')
    assert first_start is not None
    first_turn_id = first_start['turn_id']
    assert first_start['rules_hint']['outcome_deferred'] is True

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I roll a d20: 17',
        },
    )
    second_events = client.get_received()
    second_start = _event_payload(second_events, 'dm_response_start')
    assert second_start is not None
    assert second_start['rules_hint']['roll_value'] == 17
    assert second_start['rules_hint']['resolved_turn_id'] == first_turn_id
    assert second_start['rules_hint']['roll_type'] == 'attack'

    with app.app_context():
        first_turn = db.session.get(DmTurn, first_turn_id)
        assert first_turn is not None
        assert first_turn.outcome_status == 'resolved'

        second_turn = DmTurn.query.order_by(DmTurn.turn_id.desc()).first()
        assert second_turn is not None
        assert second_turn.roll_value == 17
        assert second_turn.rule_type == 'attack'
        assert second_turn.outcome_status == 'resolved'


def test_roll_can_target_specific_pending_turn(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The targeted check resolves.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    with app.app_context():
        older = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I inspect the first ward.',
            requires_roll=True,
            rule_type='lore',
            confidence=0.7,
            outcome_status='deferred',
            rules_hint=safe_json_dumps({'dc_hint': '14'}, {}),
            status='completed',
        )
        newer = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I creep past the second ward.',
            requires_roll=True,
            rule_type='stealth',
            confidence=0.8,
            outcome_status='deferred',
            rules_hint=safe_json_dumps({'dc_hint': '16'}, {}),
            status='completed',
        )
        db.session.add_all([older, newer])
        db.session.commit()
        older_turn_id = older.turn_id
        newer_turn_id = newer.turn_id

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()
    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I roll a d20 for the first ward: 18',
            'action_intent': {
                'kind': 'roll',
                'source': 'dice_roller',
                'client_message_id': 'target-old-pending',
                'roll': {
                    'die': 'd20',
                    'mode': 'normal',
                    'modifier': 0,
                    'rolls': [18],
                    'kept': 18,
                    'total': 18,
                    'result_visibility': 'hidden_until_landed',
                    'reason': 'first ward',
                    'target_pending_turn_id': older_turn_id,
                },
            },
        },
    )
    events = client.get_received()
    start = _event_payload(events, 'dm_response_start')
    assert start is not None
    assert start['rules_hint']['resolved_turn_id'] == older_turn_id
    assert start['rules_hint']['target_pending_turn_id'] == older_turn_id
    assert start['rules_hint']['roll_type'] == 'lore'

    with app.app_context():
        older_turn = db.session.get(DmTurn, older_turn_id)
        newer_turn = db.session.get(DmTurn, newer_turn_id)
        assert older_turn.outcome_status == 'resolved'
        assert newer_turn.outcome_status == 'deferred'


def test_pending_check_blocks_new_action_until_roll_is_provided(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The enemy squares up for the exchange.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin.',
        },
    )
    first_events = client.get_received()
    first_start = _event_payload(first_events, 'dm_response_start')
    assert first_start is not None
    first_turn_id = first_start['turn_id']

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I open the chest and move on.',
        },
    )
    blocked_events = client.get_received()
    error_payload = _event_payload(blocked_events, 'error')
    roll_required_payload = _event_payload(blocked_events, 'roll_required')

    assert error_payload is not None
    assert error_payload['error_code'] == 'roll_required'
    assert roll_required_payload is not None
    assert roll_required_payload['pending_turn_id'] == first_turn_id
    assert roll_required_payload['rule_type'] == 'attack'

    with app.app_context():
        turn_count = DmTurn.query.filter_by(session_id=ids['session_id']).count()
        assert turn_count == 1


def test_injects_roll_prompt_when_model_omits_it(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'Steel rings out and the goblin lunges.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin.',
        },
    )
    events = client.get_received()
    chunks = []
    for event in events:
        if event['name'] != 'dm_chunk':
            continue
        payload = event['args'][0] if event['args'] else {}
        chunks.append(payload.get('chunk', ''))

    combined = ''.join(chunks)
    assert 'Please roll' in combined


def test_injects_roll_prompt_when_response_uses_non_request_check_word(app, socketio, app_runtime, monkeypatch):
    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'You check the corridor and steel flashes in the dark.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

    ids = seed_world_campaign_player_session(app)
    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': ids['player_id']})
    client.get_received()

    client.emit(
        'send_message',
        {
            'session_id': ids['session_id'],
            'campaign_id': ids['campaign_id'],
            'world_id': ids['world_id'],
            'player_id': ids['player_id'],
            'message': 'I attack the goblin.',
        },
    )
    events = client.get_received()
    combined = ''.join(
        (event['args'][0].get('chunk', '') if event.get('args') else '')
        for event in events
        if event['name'] == 'dm_chunk'
    )

    assert 'Please roll' in combined
