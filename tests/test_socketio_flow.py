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

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The corridor hums with ancient magic.'

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)

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


def test_turn_persist_failure_is_emitted_to_client(app, socketio, app_runtime, monkeypatch):
    import aidm_server.turn_engine as turn_engine_module

    socketio_module = app_runtime['modules']['socketio_events']

    def fake_stream(user_input, context, speaking_player=None, rules_hint=None):
        yield 'The corridor hums with ancient magic.'

    def fail_apply_canon_patch(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(socketio_module, 'query_dm_function_stream', fake_stream)
    monkeypatch.setattr(turn_engine_module, 'apply_canon_patch', fail_apply_canon_patch)

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
    error_payload = _event_payload(received, 'error')

    assert error_payload is not None
    assert error_payload['error_code'] == 'turn_persist_failed'
    assert error_payload['details']['session_id'] == ids['session_id']


def test_join_session_rejects_player_from_other_campaign(app, socketio, app_runtime):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        other_world = World(name='Other World', description='Separate test world')
        db.session.add(other_world)
        db.session.flush()
        other_campaign = Campaign(title='Other Campaign', world_id=other_world.world_id)
        db.session.add(other_campaign)
        db.session.flush()
        other_player = Player(campaign_id=other_campaign.campaign_id, name='Bob', character_name='Bob')
        db.session.add(other_player)
        db.session.commit()
        other_player_id = other_player.player_id

    client = socketio.test_client(app, flask_test_client=app.test_client())
    assert client.is_connected()

    client.emit('join_session', {'session_id': ids['session_id'], 'player_id': other_player_id})
    received = client.get_received()
    error_payload = _event_payload(received, 'error')

    assert error_payload is not None
    assert error_payload['error_code'] == 'campaign_mismatch'
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
