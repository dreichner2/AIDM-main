from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import DmTurn, Session
from tests.helpers import seed_world_campaign_player_session


def test_submit_feedback_and_beta_summary(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        turn_ok = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I attack.',
            dm_output='You strike true.',
            requires_roll=True,
            rule_type='attack',
            confidence=0.9,
            outcome_status='resolved',
            status='completed',
            latency_ms=120,
        )
        turn_failed = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I cast a spell.',
            dm_output='',
            requires_roll=False,
            rule_type=None,
            confidence=0.7,
            outcome_status='resolved',
            status='failed',
            latency_ms=300,
        )
        db.session.add(turn_ok)
        db.session.add(turn_failed)

        session_obj = db.session.get(Session, ids['session_id'])
        session_obj.state_snapshot = '{"recap":"done"}'
        db.session.commit()

        turn_id = turn_ok.turn_id

    feedback_response = client.post(
        '/api/feedback/coherence',
        json={
            'session_id': ids['session_id'],
            'turn_id': turn_id,
            'coherence_score': 4,
            'notes': 'Solid continuity',
        },
    )
    assert feedback_response.status_code == 201
    assert feedback_response.get_json()['feedback_id'] > 0

    summary_response = client.get('/api/beta/summary')
    assert summary_response.status_code == 200
    payload = summary_response.get_json()

    assert payload['turn_latency_ms_avg'] is not None
    assert payload['ai_failure_rate'] > 0.0
    assert payload['session_completion_rate'] == 1.0
    assert payload['coherence_feedback_avg'] == 4.0
    assert payload['coherence_feedback_count'] == 1


def test_feedback_validation_errors(client):
    response = client.post('/api/feedback/coherence', json={'session_id': 1})
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'

    response = client.post('/api/feedback/coherence', json={'session_id': 1, 'coherence_score': 7})
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'
