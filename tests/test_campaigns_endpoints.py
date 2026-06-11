from __future__ import annotations

import json

from aidm_server.database import db
from aidm_server.models import (
    Campaign,
    CampaignSegment,
    BestiaryEntry,
    CanonJob,
    DmCoherenceFeedback,
    DmTurn,
    Map,
    Player,
    PlayerAction,
    Session,
    SessionLogEntry,
    SessionState,
    StoryEntity,
    StoryFact,
    StoryThread,
    TurnCanonUpdate,
    TurnEvent,
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
    payload = response.get_json()
    campaign_id = payload['campaign_id']
    assert payload['world_name'] == 'Campaign World'
    assert payload['bestiary_seeded_count'] == 8

    with app.app_context():
        campaign = db.session.get(Campaign, campaign_id)
        assert campaign is not None
        assert campaign.title == 'Gate of Ash'
        assert campaign.world_id == world_id
        assert campaign.status == 'active'
        assert BestiaryEntry.query.filter_by(campaign_id=campaign_id, source='campaign_pack').count() == 8


def test_create_campaign_can_opt_out_of_bestiary_seed(client, app):
    with app.app_context():
        world = World(name='Empty Campaign World', description='For opt out')
        db.session.add(world)
        db.session.commit()
        world_id = world.world_id

    response = client.post(
        '/api/campaigns',
        json={
            'title': 'Quiet Table',
            'world_id': world_id,
            'seed_bestiary': False,
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload['bestiary_seeded_count'] == 0
    with app.app_context():
        assert BestiaryEntry.query.filter_by(campaign_id=payload['campaign_id']).count() == 0


def test_create_campaign_rejects_invalid_world_id(client):
    response = client.post('/api/campaigns', json={'title': 'Broken', 'world_id': 'nope'})

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'


def test_create_campaign_rejects_non_string_text_fields(client, app):
    with app.app_context():
        world = World(name='Text Validation World', description='For validation')
        db.session.add(world)
        db.session.commit()
        world_id = world.world_id

    response = client.post('/api/campaigns', json={'title': 123, 'world_id': world_id})

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
    assert campaign_payload['updated_at']
    assert campaign_payload['status'] == 'active'
    assert campaign_payload['is_archived'] is False
    assert campaign_payload['world_name'] == 'Test World'


def test_update_campaign_validates_and_persists_metadata(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.patch(
        f"/api/campaigns/{ids['campaign_id']}",
        json={
            'title': '  Smoke Over Ember  ',
            'description': 'A cleaner campaign description.',
            'current_quest': 'Find the red bell',
            'location': 'Ash Market',
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['title'] == 'Smoke Over Ember'
    assert payload['description'] == 'A cleaner campaign description.'
    assert payload['current_quest'] == 'Find the red bell'
    assert payload['location'] == 'Ash Market'
    assert payload['updated_at']

    empty_title_response = client.patch(f"/api/campaigns/{ids['campaign_id']}", json={'title': '  '})
    assert empty_title_response.status_code == 400
    assert empty_title_response.get_json()['error_code'] == 'validation_error'


def test_update_campaign_rejects_stale_expected_updated_at(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.patch(
        f"/api/campaigns/{ids['campaign_id']}",
        json={'title': 'Stale Title', 'expected_updated_at': '1999-01-01T00:00:00'},
    )

    assert response.status_code == 409
    assert response.get_json()['error_code'] == 'stale_update'


def test_campaign_archive_delete_and_restore_hide_from_default_lists(client, app):
    ids = seed_world_campaign_player_session(app)
    with app.app_context():
        manually_archived = Session(
            campaign_id=ids['campaign_id'],
            name='Already Archived',
            status='archived',
        )
        db.session.add(manually_archived)
        db.session.commit()
        manually_archived_id = manually_archived.session_id

    archive_response = client.delete(f"/api/campaigns/{ids['campaign_id']}")
    assert archive_response.status_code == 200
    archive_payload = archive_response.get_json()
    assert archive_payload['archived'] is True
    assert archive_payload['campaign']['status'] == 'archived'

    list_response = client.get('/api/campaigns')
    assert list_response.status_code == 200
    assert all(item['campaign_id'] != ids['campaign_id'] for item in list_response.get_json())

    workspace_response = client.get(f"/api/campaigns/{ids['campaign_id']}/workspace")
    assert workspace_response.status_code == 404
    assert workspace_response.get_json()['error_code'] == 'campaign_not_found'

    archived_workspace_response = client.get(f"/api/campaigns/{ids['campaign_id']}/workspace?include_archived=true")
    assert archived_workspace_response.status_code == 200
    assert archived_workspace_response.get_json()['campaign']['is_archived'] is True

    archived_list_response = client.get('/api/campaigns?include_archived=true')
    assert archived_list_response.status_code == 200
    archived = next(item for item in archived_list_response.get_json() if item['campaign_id'] == ids['campaign_id'])
    assert archived['is_archived'] is True

    with app.app_context():
        session = db.session.get(Session, ids['session_id'])
        assert session is not None
        assert session.status == 'archived'
        assert session.archived_by_campaign_id == ids['campaign_id']

    restore_response = client.post(f"/api/campaigns/{ids['campaign_id']}/restore")
    assert restore_response.status_code == 200
    assert restore_response.get_json()['campaign']['status'] == 'active'

    with app.app_context():
        restored_session = db.session.get(Session, ids['session_id'])
        manually_archived = db.session.get(Session, manually_archived_id)
        assert restored_session is not None
        assert restored_session.status == 'active'
        assert restored_session.archived_by_campaign_id is None
        assert manually_archived is not None
        assert manually_archived.status == 'archived'
        assert manually_archived.archived_by_campaign_id is None


def test_campaign_hard_delete_rejects_campaigns_with_sessions(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.delete(f"/api/campaigns/{ids['campaign_id']}?hard=true")

    assert response.status_code == 409
    assert response.get_json()['error_code'] == 'campaign_has_sessions'


def test_campaign_force_hard_delete_removes_campaign_workspace(client, app):
    ids = seed_world_campaign_player_session(app)
    with app.app_context():
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I inspect the doomed gate.',
            dm_output='The gate is ready to be deleted.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add(turn)
        db.session.flush()
        db.session.add_all(
            [
                TurnCanonUpdate(turn_id=turn.turn_id, campaign_id=ids['campaign_id']),
                CanonJob(
                    turn_id=turn.turn_id,
                    campaign_id=ids['campaign_id'],
                    session_id=ids['session_id'],
                ),
                TurnEvent(
                    session_id=ids['session_id'],
                    campaign_id=ids['campaign_id'],
                    turn_id=turn.turn_id,
                    player_id=ids['player_id'],
                    event_type='delete_test',
                    payload_json='{}',
                ),
                SessionLogEntry(session_id=ids['session_id'], message='delete log', entry_type='dm'),
                SessionState(session_id=ids['session_id'], rolling_summary='delete summary'),
                PlayerAction(
                    player_id=ids['player_id'],
                    session_id=ids['session_id'],
                    action_text='I inspect the doomed gate.',
                ),
                DmCoherenceFeedback(
                    session_id=ids['session_id'],
                    turn_id=turn.turn_id,
                    coherence_score=5,
                ),
            ]
        )
        db.session.add(Map(world_id=ids['world_id'], campaign_id=ids['campaign_id'], title='Delete Map'))
        db.session.add(CampaignSegment(campaign_id=ids['campaign_id'], title='Delete Segment'))
        db.session.add(StoryEntity(campaign_id=ids['campaign_id'], entity_type='npc', name='Delete NPC'))
        db.session.flush()
        entity = StoryEntity.query.filter_by(campaign_id=ids['campaign_id']).first()
        assert entity is not None
        db.session.add(StoryFact(campaign_id=ids['campaign_id'], subject_entity_id=entity.entity_id, predicate='knows'))
        db.session.add(StoryThread(campaign_id=ids['campaign_id'], title='Delete Thread'))
        db.session.commit()

    response = client.delete(f"/api/campaigns/{ids['campaign_id']}?hard=true&force=true")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['deleted'] is True
    assert payload['hard_deleted'] is True
    assert payload['deleted_session_ids'] == [ids['session_id']]

    assert client.get(f"/api/campaigns/{ids['campaign_id']}").status_code == 404
    with app.app_context():
        assert db.session.get(Campaign, ids['campaign_id']) is None
        assert db.session.get(Session, ids['session_id']) is None
        player = db.session.get(Player, ids['player_id'])
        assert player is not None
        assert player.campaign_id is None
        assert player.workspace_id == 'owner'
        assert Map.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert CampaignSegment.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert StoryFact.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert StoryEntity.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert DmTurn.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert TurnCanonUpdate.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert CanonJob.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert TurnEvent.query.filter_by(campaign_id=ids['campaign_id']).count() == 0
        assert SessionLogEntry.query.filter_by(session_id=ids['session_id']).count() == 0
        assert SessionState.query.filter_by(session_id=ids['session_id']).count() == 0
        assert PlayerAction.query.filter_by(session_id=ids['session_id']).count() == 0
        assert DmCoherenceFeedback.query.filter_by(session_id=ids['session_id']).count() == 0


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
    assert payload['has_more'] == {
        'sessions': False,
        'players': False,
        'maps': False,
        'segments': False,
    }
    assert payload['next_cursor'] == {
        'sessions': None,
        'players': None,
        'maps': None,
        'segments': None,
    }
    assert payload['sessions'][0]['turn_count'] == 1
    assert payload['sessions'][0]['latest_summary'] == 'The party found the Ash Gate.'
    assert payload['players'][0]['player_id'] == ids['player_id']
    assert payload['maps'][0]['map_data'] == {'tiles': []}
    assert payload['segments'][0]['title'] == 'Hidden Chamber'


def test_campaign_workspace_summary_counts_full_collection_when_lists_are_limited(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        db.session.add_all(
            [
                Session(campaign_id=ids['campaign_id']),
                Session(campaign_id=ids['campaign_id']),
                Player(
                    campaign_id=ids['campaign_id'],
                    name='Bob',
                    character_name='Mira',
                    race='Human',
                    class_='Fighter',
                    level=1,
                ),
                Map(
                    world_id=ids['world_id'],
                    campaign_id=ids['campaign_id'],
                    title='Second Map',
                    description='Another place.',
                    map_data=json.dumps({}),
                ),
                Map(
                    world_id=ids['world_id'],
                    campaign_id=ids['campaign_id'],
                    title='Third Map',
                    description='Another place.',
                    map_data=json.dumps({}),
                ),
                CampaignSegment(
                    campaign_id=ids['campaign_id'],
                    title='Second Segment',
                    description='Another segment.',
                    trigger_condition='later',
                    tags='later',
                    is_triggered=False,
                ),
                CampaignSegment(
                    campaign_id=ids['campaign_id'],
                    title='Third Segment',
                    description='Another segment.',
                    trigger_condition='later',
                    tags='later',
                    is_triggered=False,
                ),
            ]
        )
        db.session.commit()

    response = client.get(
        f"/api/campaigns/{ids['campaign_id']}/workspace"
        "?session_limit=1&player_limit=1&map_limit=1&segment_limit=1"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['summary']['session_count'] == 3
    assert payload['summary']['player_count'] == 2
    assert payload['summary']['map_count'] == 2
    assert payload['summary']['segment_count'] == 2
    assert len(payload['sessions']) == 1
    assert len(payload['players']) == 1
    assert len(payload['maps']) == 1
    assert len(payload['segments']) == 1
    assert payload['has_more'] == {
        'sessions': True,
        'players': True,
        'maps': True,
        'segments': True,
    }


def test_campaign_canon_endpoint_paginates_collections(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        entities = [
            StoryEntity(
                campaign_id=ids['campaign_id'],
                session_id=ids['session_id'],
                entity_type='npc',
                name=f'Entity {index}',
                canonical_name=f'entity-{index}',
                summary='A test entity.',
            )
            for index in range(3)
        ]
        db.session.add_all(entities)
        db.session.flush()
        turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I remember.',
            dm_output='A memory forms.',
            status='completed',
            outcome_status='resolved',
        )
        db.session.add(turn)
        db.session.flush()
        facts = [
            StoryFact(
                campaign_id=ids['campaign_id'],
                subject_entity_id=entities[index % len(entities)].entity_id,
                predicate='knows',
                value_text=f'Fact {index}',
                fact_status='accepted',
            )
            for index in range(3)
        ]
        threads = [
            StoryThread(
                campaign_id=ids['campaign_id'],
                title=f'Thread {index}',
                summary='A thread.',
                status='open',
            )
            for index in range(3)
        ]
        updates = [
            TurnCanonUpdate(
                turn_id=turn.turn_id,
                campaign_id=ids['campaign_id'],
                raw_patch_json='{}',
                applied_patch_json='{}',
                status='applied',
            )
            for _index in range(3)
        ]
        db.session.add_all(facts + threads + updates)
        db.session.commit()

    response = client.get(f"/api/campaigns/{ids['campaign_id']}/canon?limit=2")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload['entities']) == 2
    assert len(payload['facts']) == 2
    assert len(payload['threads']) == 2
    assert len(payload['updates']) == 2
    assert payload['has_more']['entities'] is True
    assert payload['has_more']['facts'] is True
    assert payload['next_cursor']['facts'] is not None
    assert payload['facts'][0]['subject_name'].startswith('Entity')

    next_response = client.get(
        f"/api/campaigns/{ids['campaign_id']}/canon?limit=2"
        f"&fact_before_id={payload['next_cursor']['facts']}"
    )
    assert next_response.status_code == 200
    assert len(next_response.get_json()['facts']) == 1


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
        'canon_job_counts': {},
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
