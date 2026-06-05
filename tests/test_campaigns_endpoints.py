from __future__ import annotations

import json

from aidm_server.database import db
from aidm_server.models import (
    Campaign,
    CampaignSegment,
    DmTurn,
    Map,
    SessionLogEntry,
    SessionState,
    StoryEntity,
    StoryFact,
    StoryThread,
    TurnCanonUpdate,
    World,
)
from tests.helpers import seed_world_campaign_player_session


def test_create_campaign_accepts_numeric_world_id_string(client, app):
    with app.app_context():
        world = World(name='Campaign World', description='For campaign creation')
        db.session.add(world)
        db.session.commit()
        world_id = world.world_id

    response = client.post(
        '/api/campaigns',
        json={
            'title': '  Gate of Ash  ',
            'world_id': str(world_id),
            'description': 'A new table.',
        },
    )

    assert response.status_code == 201
    campaign_id = response.get_json()['campaign_id']

    with app.app_context():
        campaign = db.session.get(Campaign, campaign_id)
        assert campaign is not None
        assert campaign.title == 'Gate of Ash'
        assert campaign.world_id == world_id


def test_create_campaign_rejects_invalid_world_id(client):
    response = client.post('/api/campaigns', json={'title': 'Broken', 'world_id': 'nope'})

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'


def test_create_campaign_requires_json_body(client):
    response = client.post('/api/campaigns', data='not-json', content_type='text/plain')

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'


def test_create_campaign_rejects_overlong_text_fields(client, app):
    with app.app_context():
        world = World(name='Validation World', description='For validation')
        db.session.add(world)
        db.session.commit()
        world_id = world.world_id

    title_response = client.post(
        '/api/campaigns',
        json={'title': 'x' * 121, 'world_id': world_id},
    )
    assert title_response.status_code == 400
    assert title_response.get_json()['error_code'] == 'validation_error'

    description_response = client.post(
        '/api/campaigns',
        json={'title': 'Valid Title', 'world_id': world_id, 'description': 'x' * 2001},
    )
    assert description_response.status_code == 400
    assert description_response.get_json()['error_code'] == 'validation_error'


def test_list_campaigns_returns_compact_session_summary(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I inspect the gate.',
            dm_output='The gate hums.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add(turn)
        db.session.add(SessionLogEntry(session_id=ids['session_id'], message='The gate hums.', entry_type='dm'))
        db.session.commit()

    response = client.get('/api/campaigns')

    assert response.status_code == 200
    payload = response.get_json()
    campaign_payload = next(item for item in payload if item['campaign_id'] == ids['campaign_id'])
    assert campaign_payload['session_count'] == 1
    assert campaign_payload['latest_session_id'] == ids['session_id']
    assert campaign_payload['latest_activity_at']


def test_campaign_workspace_endpoint_returns_aggregate_payload(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        map_obj = Map(
            world_id=ids['world_id'],
            campaign_id=ids['campaign_id'],
            title='Ash Gate',
            description='A gate under black rain.',
            map_data=json.dumps({'tiles': []}),
        )
        segment = CampaignSegment(
            campaign_id=ids['campaign_id'],
            title='Hidden Chamber',
            description='The hidden chamber opens.',
            trigger_condition='sigil solved',
            tags='chamber,secret',
            is_triggered=False,
        )
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I inspect the gate.',
            dm_output='The gate hums.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add_all([map_obj, segment, turn])
        db.session.flush()
        db.session.add(SessionLogEntry(session_id=ids['session_id'], message='The gate hums.', entry_type='dm'))
        db.session.add(SessionState(session_id=ids['session_id'], rolling_summary='The party found the Ash Gate.'))
        db.session.commit()

    response = client.get(f"/api/campaigns/{ids['campaign_id']}/workspace")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['campaign']['campaign_id'] == ids['campaign_id']
    assert payload['summary']['session_count'] == 1
    assert payload['summary']['player_count'] == 1
    assert payload['summary']['map_count'] == 1
    assert payload['summary']['segment_count'] == 1
    assert payload['summary']['latest_session_id'] == ids['session_id']
    assert payload['sessions'][0]['turn_count'] == 1
    assert payload['sessions'][0]['latest_summary'] == 'The party found the Ash Gate.'
    assert payload['players'][0]['player_id'] == ids['player_id']
    assert payload['maps'][0]['map_data'] == {'tiles': []}
    assert payload['segments'][0]['title'] == 'Hidden Chamber'


def test_campaign_canon_endpoint_returns_structured_story_state(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I read the sigil.',
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
            canonical_name='The Amber Gate',
            summary='A sealed entrance.',
            aliases_json=json.dumps(['Gate of Amber']),
            metadata_json=json.dumps({'danger': 'high'}),
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
            value_json=json.dumps({'seal': 'sigil'}),
            confidence=0.88,
            source_turn_id=turn.turn_id,
        )
        thread = StoryThread(
            campaign_id=ids['campaign_id'],
            title='Open the Amber Gate',
            summary='The party needs the seal phrase.',
            origin_turn_id=turn.turn_id,
            last_touched_turn_id=turn.turn_id,
            metadata_json=json.dumps({'priority_reason': 'main path'}),
        )
        update = TurnCanonUpdate(
            turn_id=turn.turn_id,
            campaign_id=ids['campaign_id'],
            raw_patch_json=json.dumps({'entities': ['Amber Gate']}),
            applied_patch_json=json.dumps({'accepted': True}),
            status='applied',
            extractor_model='test-extractor',
        )
        db.session.add_all([fact, thread, update])
        db.session.commit()

    response = client.get(f"/api/campaigns/{ids['campaign_id']}/canon")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['campaign_id'] == ids['campaign_id']
    assert payload['summary'] == {
        'entity_count': 1,
        'fact_count': 1,
        'thread_count': 1,
        'update_count': 1,
    }
    assert payload['entities'][0]['aliases'] == ['Gate of Amber']
    assert payload['entities'][0]['metadata'] == {'danger': 'high'}
    assert payload['facts'][0]['subject_name'] == 'Amber Gate'
    assert payload['facts'][0]['value_json'] == {'seal': 'sigil'}
    assert payload['threads'][0]['metadata'] == {'priority_reason': 'main path'}
    assert payload['updates'][0]['applied_patch'] == {'accepted': True}


def test_campaign_workspace_and_canon_return_404_for_missing_campaign(client):
    workspace_response = client.get('/api/campaigns/99999/workspace')
    canon_response = client.get('/api/campaigns/99999/canon')

    assert workspace_response.status_code == 404
    assert workspace_response.get_json()['error_code'] == 'campaign_not_found'
    assert canon_response.status_code == 404
    assert canon_response.get_json()['error_code'] == 'campaign_not_found'
