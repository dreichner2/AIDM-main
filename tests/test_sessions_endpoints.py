from __future__ import annotations

import json

import aidm_server.blueprints.sessions as sessions_blueprint
from aidm_server.database import db
from aidm_server.models import (
    DmTurn,
    Session,
    SessionLogEntry,
    SessionState,
    StoryEntity,
    StoryFact,
    StoryThread,
    TurnEvent,
    TurnCanonUpdate,
)
from tests.helpers import seed_world_campaign_player_session


def test_session_state_and_log_endpoints(client, app):
    ids = seed_world_campaign_player_session(app)

    state_response = client.get(f"/api/sessions/{ids['session_id']}/state")
    assert state_response.status_code == 200
    state_payload = state_response.get_json()
    assert state_payload['session_id'] == ids['session_id']
    assert 'rolling_summary' in state_payload
    assert state_payload['current_location'] == 'Old Ruins'
    assert state_payload['current_quest'] == 'Find the relic'

    with app.app_context():
        assert SessionState.query.filter_by(session_id=ids['session_id']).first() is None

    log_response = client.get(f"/api/sessions/{ids['session_id']}/log")
    assert log_response.status_code == 200
    log_payload = log_response.get_json()
    assert log_payload['session_id'] == ids['session_id']
    assert isinstance(log_payload['entries'], list)


def test_end_session_recap_persists_snapshot(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.post(f"/api/sessions/{ids['session_id']}/end")
    assert response.status_code == 200
    payload = response.get_json()
    assert 'recap' in payload

    sessions_response = client.get(f"/api/sessions/campaigns/{ids['campaign_id']}/sessions")
    assert sessions_response.status_code == 200
    sessions_payload = sessions_response.get_json()
    assert isinstance(sessions_payload[0]['state_snapshot'], dict)
    assert sessions_payload[0]['state_snapshot']['recap'] == payload['recap']


def test_end_session_recap_uses_bounded_recent_log_and_summary(client, app, monkeypatch):
    ids = seed_world_campaign_player_session(app)
    captured = {}

    with app.app_context():
        db.session.add(
            SessionState(
                session_id=ids['session_id'],
                rolling_summary='Campaign summary before the bounded batch.',
            )
        )
        db.session.add_all(
            [
                SessionLogEntry(
                    session_id=ids['session_id'],
                    message=f'ancient-log-{index}',
                    entry_type='dm',
                )
                for index in range(20)
            ]
        )
        db.session.add_all(
            [
                SessionLogEntry(
                    session_id=ids['session_id'],
                    message=f'recent-log-{index}',
                    entry_type='dm',
                )
                for index in range(80)
            ]
        )
        db.session.commit()

    def fake_query_gpt(prompt, system_message=None):
        captured['prompt'] = prompt
        captured['system_message'] = system_message
        return 'bounded recap'

    monkeypatch.setattr(sessions_blueprint, 'query_gpt', fake_query_gpt)

    response = client.post(f"/api/sessions/{ids['session_id']}/end")

    assert response.status_code == 200
    assert response.get_json()['recap'] == 'bounded recap'
    assert captured['system_message'] == 'You are a D&D session summarizer.'
    assert 'Campaign summary before the bounded batch.' in captured['prompt']
    assert 'recent-log-79' in captured['prompt']
    assert 'ancient-log-0' not in captured['prompt']


def test_start_session_adds_welcome_log(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.post('/api/sessions/start', json={'campaign_id': ids['campaign_id']})
    assert response.status_code == 201
    session_id = response.get_json()['session_id']

    log_response = client.get(f'/api/sessions/{session_id}/log')
    assert log_response.status_code == 200
    entries = log_response.get_json()['entries']

    assert entries[0]['entry_type'] == 'system'
    assert 'Welcome to the table' in entries[0]['message']


def test_update_session_persists_name_in_snapshot(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.patch(f"/api/sessions/{ids['session_id']}", json={'name': 'Pyres at Dawn'})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['state_snapshot']['name'] == 'Pyres at Dawn'
    assert payload['display_name'] == 'Pyres at Dawn'
    assert payload['updated_at']

    sessions_response = client.get(f"/api/sessions/campaigns/{ids['campaign_id']}/sessions")
    assert sessions_response.status_code == 200
    sessions_payload = sessions_response.get_json()
    renamed = next(item for item in sessions_payload if item['session_id'] == ids['session_id'])
    assert renamed['state_snapshot']['name'] == 'Pyres at Dawn'
    assert renamed['display_name'] == 'Pyres at Dawn'
    assert renamed['latest_activity_at']
    assert renamed['turn_count'] == 0
    assert renamed['latest_summary'] == ''


def test_list_campaign_sessions_includes_display_metadata(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I inspect the relic.',
            dm_output='It glows blue.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add(turn)
        db.session.flush()
        db.session.add(SessionLogEntry(session_id=ids['session_id'], message='It glows blue.', entry_type='dm'))
        db.session.add(SessionState(session_id=ids['session_id'], rolling_summary='The relic started glowing.'))
        db.session.commit()

    response = client.get(f"/api/sessions/campaigns/{ids['campaign_id']}/sessions")

    assert response.status_code == 200
    payload = response.get_json()[0]
    assert payload['session_id'] == ids['session_id']
    assert payload['display_name'] == f"Session {ids['session_id']}"
    assert payload['turn_count'] == 1
    assert payload['latest_summary'] == 'The relic started glowing.'
    assert payload['latest_activity_at']
    assert payload['updated_at']
    assert payload['is_archived'] is False


def test_update_session_rejects_empty_and_overlong_names(client, app):
    ids = seed_world_campaign_player_session(app)

    empty_response = client.patch(f"/api/sessions/{ids['session_id']}", json={'name': '   '})
    assert empty_response.status_code == 400
    assert empty_response.get_json()['error_code'] == 'validation_error'

    overlong_response = client.patch(f"/api/sessions/{ids['session_id']}", json={'name': 'x' * 81})
    assert overlong_response.status_code == 400
    assert overlong_response.get_json()['error_code'] == 'validation_error'


def test_update_missing_session_returns_404(client):
    response = client.patch('/api/sessions/99999', json={'name': 'Missing Session'})

    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'session_not_found'


def test_delete_session_removes_session_owned_rows(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I listen.',
            dm_output='Ash falls.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add(turn)
        db.session.flush()
        db.session.add(TurnCanonUpdate(turn_id=turn.turn_id, campaign_id=ids['campaign_id']))
        db.session.add(SessionLogEntry(session_id=ids['session_id'], message='log', entry_type='dm'))
        db.session.add(SessionState(session_id=ids['session_id'], rolling_summary='summary'))
        db.session.commit()
        turn_id = turn.turn_id

    response = client.delete(f"/api/sessions/{ids['session_id']}")
    assert response.status_code == 200
    assert response.get_json()['deleted'] is True

    with app.app_context():
        assert db.session.get(Session, ids['session_id']) is None
        assert DmTurn.query.filter_by(session_id=ids['session_id']).count() == 0
        assert SessionLogEntry.query.filter_by(session_id=ids['session_id']).count() == 0
        assert SessionState.query.filter_by(session_id=ids['session_id']).count() == 0
        assert TurnCanonUpdate.query.filter_by(turn_id=turn_id).count() == 0


def test_delete_session_clears_canon_turn_references(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I study the sigil.',
            dm_output='It names the Amber Gate.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add(turn)
        db.session.flush()
        entity = StoryEntity(
            campaign_id=ids['campaign_id'],
            session_id=ids['session_id'],
            entity_type='location',
            name='Amber Gate',
            first_seen_turn_id=turn.turn_id,
            last_seen_turn_id=turn.turn_id,
        )
        db.session.add(entity)
        db.session.flush()
        fact = StoryFact(
            campaign_id=ids['campaign_id'],
            subject_entity_id=entity.entity_id,
            predicate='is sealed by',
            value_text='a rain-worn sigil',
            source_turn_id=turn.turn_id,
        )
        thread = StoryThread(
            campaign_id=ids['campaign_id'],
            title='Open the Amber Gate',
            origin_turn_id=turn.turn_id,
            last_touched_turn_id=turn.turn_id,
            resolved_turn_id=turn.turn_id,
        )
        db.session.add_all([fact, thread])
        db.session.commit()
        entity_id = entity.entity_id
        fact_id = fact.fact_id
        thread_id = thread.thread_id

    response = client.delete(f"/api/sessions/{ids['session_id']}")
    assert response.status_code == 200

    with app.app_context():
        entity = db.session.get(StoryEntity, entity_id)
        fact = db.session.get(StoryFact, fact_id)
        thread = db.session.get(StoryThread, thread_id)
        assert entity is not None
        assert entity.session_id is None
        assert entity.first_seen_turn_id is None
        assert entity.last_seen_turn_id is None
        assert fact is not None
        assert fact.source_turn_id is None
        assert thread is not None
        assert thread.origin_turn_id is None
        assert thread.last_touched_turn_id is None
        assert thread.resolved_turn_id is None


def test_delete_missing_and_repeated_session_returns_404(client, app):
    ids = seed_world_campaign_player_session(app)

    missing_response = client.delete('/api/sessions/99999')
    assert missing_response.status_code == 404
    assert missing_response.get_json()['error_code'] == 'session_not_found'

    first_response = client.delete(f"/api/sessions/{ids['session_id']}")
    assert first_response.status_code == 200

    repeated_response = client.delete(f"/api/sessions/{ids['session_id']}")
    assert repeated_response.status_code == 404
    assert repeated_response.get_json()['error_code'] == 'session_not_found'


def test_session_log_endpoint_returns_most_recent_entries_in_order(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        db.session.add_all(
            [
                SessionLogEntry(session_id=ids['session_id'], message='first', entry_type='dm'),
                SessionLogEntry(session_id=ids['session_id'], message='second', entry_type='dm'),
                SessionLogEntry(session_id=ids['session_id'], message='third', entry_type='dm'),
            ]
        )
        db.session.commit()

    response = client.get(f"/api/sessions/{ids['session_id']}/log?limit=2")
    assert response.status_code == 200
    payload = response.get_json()

    assert [entry['message'] for entry in payload['entries']] == ['second', 'third']


def test_session_events_endpoint_returns_most_recent_events_in_order(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        db.session.add_all(
            [
                TurnEvent(
                    session_id=ids['session_id'],
                    campaign_id=ids['campaign_id'],
                    player_id=ids['player_id'],
                    event_type='player_message',
                    payload_json=json.dumps({'message': 'first'}),
                ),
                TurnEvent(
                    session_id=ids['session_id'],
                    campaign_id=ids['campaign_id'],
                    player_id=ids['player_id'],
                    event_type='dm_response',
                    payload_json=json.dumps({'message': 'second'}),
                ),
                TurnEvent(
                    session_id=ids['session_id'],
                    campaign_id=ids['campaign_id'],
                    event_type='canon_applied',
                    payload_json=json.dumps({'status': 'applied'}),
                ),
            ]
        )
        db.session.commit()

    response = client.get(f"/api/sessions/{ids['session_id']}/events?limit=2")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload['session_id'] == ids['session_id']
    assert [event['event_type'] for event in payload['events']] == ['dm_response', 'canon_applied']
    assert payload['events'][0]['payload']['message'] == 'second'
    assert payload['events'][1]['payload']['status'] == 'applied'


def test_list_campaign_sessions_returns_404_for_missing_campaign(client):
    response = client.get('/api/sessions/campaigns/99999/sessions')

    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'campaign_not_found'


def test_session_events_returns_404_for_missing_session(client):
    response = client.get('/api/sessions/99999/events')

    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'session_not_found'
