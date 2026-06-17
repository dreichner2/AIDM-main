from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import Campaign, Map, Npc, Player, Session, World


def test_create_world_trims_valid_text(client, app):
    response = client.post('/api/worlds', json={'name': '  The Cinder March  ', 'description': '  Ash fields.  '})

    assert response.status_code == 201
    world_id = response.get_json()['world_id']
    with app.app_context():
        world = db.session.get(World, world_id)
        assert world is not None
        assert world.name == 'The Cinder March'
        assert world.description == 'Ash fields.'


def test_create_world_validates_request_body_and_fields(client):
    non_json_response = client.post('/api/worlds', data='not-json', content_type='text/plain')
    assert non_json_response.status_code == 400
    assert non_json_response.get_json()['error_code'] == 'validation_error'

    array_body_response = client.post('/api/worlds', json=['not', 'an', 'object'])
    assert array_body_response.status_code == 400
    assert array_body_response.get_json()['error_code'] == 'validation_error'

    empty_name_response = client.post('/api/worlds', json={'name': '   '})
    assert empty_name_response.status_code == 400
    assert empty_name_response.get_json()['error_code'] == 'validation_error'

    numeric_name_response = client.post('/api/worlds', json={'name': 123})
    assert numeric_name_response.status_code == 400
    assert numeric_name_response.get_json()['error_code'] == 'validation_error'

    overlong_name_response = client.post('/api/worlds', json={'name': 'x' * 121})
    assert overlong_name_response.status_code == 400
    assert overlong_name_response.get_json()['error_code'] == 'validation_error'

    overlong_description_response = client.post(
        '/api/worlds',
        json={'name': 'Valid World', 'description': 'x' * 2001},
    )
    assert overlong_description_response.status_code == 400
    assert overlong_description_response.get_json()['error_code'] == 'validation_error'


def test_world_list_limit_exposes_pagination_headers(client):
    for name in ('First World', 'Second World', 'Third World'):
        response = client.post('/api/worlds', json={'name': name, 'description': ''})
        assert response.status_code == 201

    response = client.get('/api/worlds?limit=2')

    assert response.status_code == 200
    assert len(response.get_json()) == 2
    assert response.headers['X-AIDM-Has-More'] == 'true'
    assert response.headers.get('X-AIDM-Next-Cursor')


def test_update_world_persists_name_and_description(client, app):
    create_response = client.post('/api/worlds', json={'name': 'Old World', 'description': 'Old description'})
    assert create_response.status_code == 201
    world_id = create_response.get_json()['world_id']

    response = client.patch(
        f'/api/worlds/{world_id}',
        json={'name': '  New World  ', 'description': '  New description.  '},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['name'] == 'New World'
    assert payload['description'] == 'New description.'
    with app.app_context():
        world = db.session.get(World, world_id)
        assert world is not None
        assert world.name == 'New World'


def test_delete_world_removes_unused_world_and_rejects_in_use_world(client, app):
    unused_response = client.post('/api/worlds', json={'name': 'Unused World', 'description': ''})
    assert unused_response.status_code == 201
    unused_world_id = unused_response.get_json()['world_id']

    delete_response = client.delete(f'/api/worlds/{unused_world_id}')
    assert delete_response.status_code == 200
    assert delete_response.get_json()['deleted'] is True
    with app.app_context():
        assert db.session.get(World, unused_world_id) is None

    in_use_response = client.post('/api/worlds', json={'name': 'Used World', 'description': ''})
    assert in_use_response.status_code == 201
    in_use_world_id = in_use_response.get_json()['world_id']
    with app.app_context():
        db.session.add(Campaign(title='Uses World', world_id=in_use_world_id))
        db.session.commit()

    blocked_response = client.delete(f'/api/worlds/{in_use_world_id}')
    assert blocked_response.status_code == 409
    payload = blocked_response.get_json()
    assert payload['error_code'] == 'world_in_use'
    assert payload['details']['campaign_count'] == 1


def test_force_delete_world_removes_active_and_archived_linked_campaigns(client, app):
    with app.app_context():
        world = World(name='Force Delete World', description='Used by campaigns')
        db.session.add(world)
        db.session.flush()
        active_campaign = Campaign(title='Active Uses World', world_id=world.world_id)
        archived_campaign = Campaign(
            title='Archived Uses World',
            world_id=world.world_id,
            status='archived',
        )
        db.session.add_all([active_campaign, archived_campaign])
        db.session.flush()
        player = Player(
            campaign_id=active_campaign.campaign_id,
            name='Aidan',
            character_name='Ash',
            race='Human',
            class_='Fighter',
            level=1,
        )
        db.session.add(player)
        db.session.add(Session(campaign_id=active_campaign.campaign_id))
        db.session.add(Session(campaign_id=archived_campaign.campaign_id, status='archived'))
        db.session.add(Map(world_id=world.world_id, title='Loose World Map'))
        db.session.add(Npc(world_id=world.world_id, name='Loose NPC'))
        db.session.commit()
        world_id = world.world_id
        active_campaign_id = active_campaign.campaign_id
        archived_campaign_id = archived_campaign.campaign_id
        player_id = player.player_id

    blocked_response = client.delete(f'/api/worlds/{world_id}')
    assert blocked_response.status_code == 409
    blocked_payload = blocked_response.get_json()
    assert blocked_payload['error_code'] == 'world_in_use'
    assert blocked_payload['details']['campaign_count'] == 2
    assert {item['status'] for item in blocked_payload['details']['campaigns']} == {'active', 'archived'}

    force_response = client.delete(f'/api/worlds/{world_id}?force=true')
    assert force_response.status_code == 200
    force_payload = force_response.get_json()
    assert force_payload['deleted'] is True
    assert force_payload['force_deleted'] is True
    assert set(force_payload['deleted_campaign_ids']) == {active_campaign_id, archived_campaign_id}

    with app.app_context():
        assert db.session.get(World, world_id) is None
        assert db.session.get(Campaign, active_campaign_id) is None
        assert db.session.get(Campaign, archived_campaign_id) is None
        assert Map.query.filter_by(world_id=world_id).count() == 0
        assert Npc.query.filter_by(world_id=world_id).count() == 0
        player = db.session.get(Player, player_id)
        assert player is not None
        assert player.campaign_id is None
