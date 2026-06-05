from __future__ import annotations

from tests.helpers import seed_world_campaign_player_session


def test_create_player_accepts_structured_inventory_and_get_returns_parsed_inventory(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.post(
        f"/api/players/campaigns/{ids['campaign_id']}/players",
        json={
            'name': 'Borin',
            'character_name': 'Borin Stoneshield',
            'inventory': [
                {'name': 'Rope', 'quantity': 2},
                'Torch',
            ],
        },
    )
    assert response.status_code == 201

    player_id = response.get_json()['player_id']
    player_response = client.get(f'/api/players/{player_id}')
    assert player_response.status_code == 200
    payload = player_response.get_json()

    assert payload['inventory'] == [
        {'name': 'Rope', 'quantity': 2},
        {'name': 'Torch', 'quantity': 1},
    ]


def test_update_player_persists_profile_sheet_stats_and_inventory(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.patch(
        f"/api/players/{ids['player_id']}",
        json={
            'name': 'Alice Updated',
            'character_name': 'Seraphina Vale',
            'race': 'Half-Elf',
            'char_class': 'Rogue',
            'level': '4',
            'stats': {'strength': 10, 'dexterity': 18},
            'character_sheet': {'current_hp': 22, 'max_hp': 28},
            'inventory': [{'name': 'Silver Key', 'quantity': 1}, 'Torch'],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['name'] == 'Alice Updated'
    assert payload['character_name'] == 'Seraphina Vale'
    assert payload['race'] == 'Half-Elf'
    assert payload['class_'] == 'Rogue'
    assert payload['char_class'] == 'Rogue'
    assert payload['level'] == 4
    assert payload['stats'] == {'strength': 10, 'dexterity': 18}
    assert payload['character_sheet'] == {'current_hp': 22, 'max_hp': 28}
    assert payload['inventory'] == [
        {'name': 'Silver Key', 'quantity': 1},
        {'name': 'Torch', 'quantity': 1},
    ]

    detail_response = client.get(f"/api/players/{ids['player_id']}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.get_json()
    assert detail_payload['stats'] == {'strength': 10, 'dexterity': 18}
    assert detail_payload['inventory'][0]['name'] == 'Silver Key'


def test_update_player_rejects_invalid_payloads(client, app):
    ids = seed_world_campaign_player_session(app)

    missing_response = client.patch('/api/players/99999', json={'name': 'Nobody'})
    assert missing_response.status_code == 404
    assert missing_response.get_json()['error_code'] == 'player_not_found'

    empty_name_response = client.patch(f"/api/players/{ids['player_id']}", json={'name': '   '})
    assert empty_name_response.status_code == 400
    assert empty_name_response.get_json()['error_code'] == 'validation_error'

    bad_level_response = client.patch(f"/api/players/{ids['player_id']}", json={'level': 21})
    assert bad_level_response.status_code == 400
    assert bad_level_response.get_json()['error_code'] == 'validation_error'


def test_list_players_returns_404_for_missing_campaign(client):
    response = client.get('/api/players/campaigns/99999/players')

    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'campaign_not_found'
