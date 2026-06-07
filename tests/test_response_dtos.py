from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import CampaignSegment, Map
from tests.helpers import seed_world_campaign_player_session


def test_shared_resource_dtos_match_workspace_and_direct_endpoints(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        map_obj = Map(
            world_id=ids['world_id'],
            campaign_id=ids['campaign_id'],
            title='Shared DTO Map',
            description='A single source of map truth.',
            map_data='{"tiles": []}',
        )
        segment = CampaignSegment(
            campaign_id=ids['campaign_id'],
            title='Shared DTO Segment',
            description='A single source of segment truth.',
            trigger_condition='when dto tests run',
            tags='test,dto',
            is_triggered=False,
        )
        db.session.add_all([map_obj, segment])
        db.session.commit()
        map_id = map_obj.map_id
        segment_id = segment.segment_id

    workspace = client.get(f"/api/campaigns/{ids['campaign_id']}/workspace").get_json()
    workspace_map = next(item for item in workspace['maps'] if item['map_id'] == map_id)
    workspace_segment = next(item for item in workspace['segments'] if item['segment_id'] == segment_id)
    workspace_player = next(item for item in workspace['players'] if item['player_id'] == ids['player_id'])

    direct_map = client.get(f'/api/maps/{map_id}').get_json()
    direct_segment = client.get(f'/api/segments/{segment_id}').get_json()
    direct_players = client.get(f"/api/players/campaigns/{ids['campaign_id']}/players").get_json()
    direct_player = next(item for item in direct_players if item['player_id'] == ids['player_id'])

    assert workspace_map == direct_map
    assert workspace_segment == direct_segment
    assert workspace_player == direct_player


def test_shared_world_dto_matches_list_and_detail_endpoints(client):
    create_response = client.post('/api/worlds', json={'name': 'DTO World', 'description': 'Shared shape.'})
    assert create_response.status_code == 201
    world_id = create_response.get_json()['world_id']

    detail_payload = client.get(f'/api/worlds/{world_id}').get_json()
    list_payload = client.get('/api/worlds').get_json()
    listed_payload = next(item for item in list_payload if item['world_id'] == world_id)

    assert detail_payload == listed_payload
