from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import CampaignSegment
from aidm_server.rules import classify_player_action
from aidm_server.segment_triggers import evaluate_segment_trigger
from tests.helpers import seed_world_campaign_player_session


def test_rules_classifier_detects_roll_requirement():
    hint = classify_player_action('I attack the goblin with my longsword')
    assert hint.requires_roll is True
    assert hint.roll_type == 'attack'
    assert hint.outcome_deferred is True
    assert hint.confidence > 0.8


def test_rules_classifier_marks_resolved_when_roll_is_provided():
    hint = classify_player_action('I attack and rolled a d20: 17')
    assert hint.requires_roll is True
    assert hint.roll_value == 17
    assert hint.outcome_deferred is False


def test_rules_classifier_detects_thieves_tools_context():
    hint = classify_player_action("I use thieves' tools to disable the ward sigil quietly.")
    assert hint.requires_roll is True
    assert hint.roll_type == 'thieves_tools'
    assert hint.outcome_deferred is True


def test_rules_classifier_detects_bluff_social_context():
    hint = classify_player_action('I bluff the guard and impersonate a city inspector.')
    assert hint.requires_roll is True
    assert hint.roll_type == 'social'


def test_rules_classifier_detects_mobility_escape_context():
    hint = classify_player_action('I sprint to the side door and leap across the rain gutter.')
    assert hint.requires_roll is True
    assert hint.roll_type == 'mobility'


def test_segment_keywords_trigger():
    trigger_condition = '{"type":"keywords","keywords":["goblin","altar"],"match":"any"}'
    matched, reason, spec = evaluate_segment_trigger(
        trigger_condition=trigger_condition,
        player_message='I search the goblin altar for clues.',
        session_state={'current_location': 'Shrine'},
        campaign_state={'location': 'Shrine', 'current_quest': 'Find relic'},
    )
    assert matched is True
    assert reason.startswith('keywords:')
    assert spec['trigger_type'] == 'keywords'


def test_create_segment_coerces_string_false_to_false(client, app):
    ids = seed_world_campaign_player_session(app)

    response = client.post(
        '/api/segments',
        json={
            'campaign_id': ids['campaign_id'],
            'title': 'Quiet Door',
            'is_triggered': 'false',
        },
    )

    assert response.status_code == 201
    segment_id = response.get_json()['segment_id']
    with app.app_context():
        segment = db.session.get(CampaignSegment, segment_id)
        assert segment is not None
        assert segment.is_triggered is False


def test_update_segment_rejects_ambiguous_boolean(client, app):
    ids = seed_world_campaign_player_session(app)
    create_response = client.post('/api/segments', json={'campaign_id': ids['campaign_id'], 'title': 'Quiet Door'})
    assert create_response.status_code == 201
    segment_id = create_response.get_json()['segment_id']

    response = client.patch(f'/api/segments/{segment_id}', json={'is_triggered': 'definitely'})

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'


def test_list_segments_returns_404_for_missing_campaign(client):
    response = client.get('/api/segments?campaign_id=99999')

    assert response.status_code == 404
    assert response.get_json()['error_code'] == 'campaign_not_found'
