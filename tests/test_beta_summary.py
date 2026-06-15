from __future__ import annotations

from aidm_server.database import db
from aidm_server.models import CanonJob, DmCoherenceFeedback, DmTurn, Session
from aidm_server.telemetry import telemetry_event
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
            llm_provider='gemini',
            llm_model='gemini-2.5-pro',
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
            llm_provider='gemini',
            llm_model='gemini-2.5-pro',
        )
        db.session.add(turn_ok)
        db.session.add(turn_failed)
        db.session.flush()
        db.session.add(
            CanonJob(
                turn_id=turn_ok.turn_id,
                session_id=ids['session_id'],
                campaign_id=ids['campaign_id'],
                status='applied',
            )
        )
        db.session.add(
            CanonJob(
                turn_id=turn_failed.turn_id,
                session_id=ids['session_id'],
                campaign_id=ids['campaign_id'],
                status='failed',
            )
        )

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

    with app.app_context():
        telemetry_event('socket.join.unauthorized')
        telemetry_event('socket.send_message.rate_limited')

    slo_response = client.get('/api/beta/slo')
    assert slo_response.status_code == 200
    slo = slo_response.get_json()
    assert slo['dm_response_latency_ms_p95'] == 300.0
    assert slo['dm_response_latency_sample_count'] == 2
    assert slo['ai_provider_failure_rate'] == 0.5
    assert slo['turn_persistence_failure_rate'] == 0.5
    assert slo['canon_job_failure_rate'] == 0.5
    assert slo['socket_unauthorized_event_count'] == 1
    assert slo['socket_rate_limited_event_count'] == 1
    assert slo['coherence_feedback_avg'] == 4.0
    assert slo['provider_model_turn_counts'] == [
        {'provider': 'gemini', 'model': 'gemini-2.5-pro', 'turn_count': 2}
    ]


def test_bad_turn_feedback_and_beta_incidents(client, app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        failed_turn = DmTurn(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            player_input='I open the wrong door.',
            dm_output='',
            status='failed',
            latency_ms=450,
            llm_provider='gemini',
            llm_model='gemini-3-flash-preview',
        )
        db.session.add(failed_turn)
        db.session.flush()
        db.session.add(
            CanonJob(
                turn_id=failed_turn.turn_id,
                session_id=ids['session_id'],
                campaign_id=ids['campaign_id'],
                status='failed',
                error_text='extractor timeout',
            )
        )
        db.session.commit()
        turn_id = failed_turn.turn_id

        telemetry_event('socket.dm_persist_failed')

    report_response = client.post(
        '/api/feedback/bad-turn',
        json={
            'session_id': ids['session_id'],
            'turn_id': turn_id,
            'category': 'rules',
            'notes': 'The result contradicted the rules prompt.',
        },
    )
    assert report_response.status_code == 201
    report_payload = report_response.get_json()['feedback']
    assert report_payload['feedback_type'] == 'bad_turn'
    assert report_payload['category'] == 'rules'
    assert report_payload['provider'] == 'gemini'
    assert report_payload['model'] == 'gemini-3-flash-preview'
    assert report_payload['turn_status'] == 'failed'

    with app.app_context():
        feedback = db.session.get(DmCoherenceFeedback, report_payload['feedback_id'])
        assert feedback.feedback_type == 'bad_turn'
        assert feedback.provider == 'gemini'
        assert feedback.model == 'gemini-3-flash-preview'

    incidents_response = client.get('/api/beta/incidents?limit=10')
    assert incidents_response.status_code == 200
    incidents_payload = incidents_response.get_json()
    incident_types = {incident['type'] for incident in incidents_payload['incidents']}
    assert {'bad_turn_report', 'failed_turn', 'failed_canon_job', 'telemetry_event'} <= incident_types
    assert incidents_payload['summary']['bad_turn_report_count'] == 1
    assert incidents_payload['summary']['failed_turn_count'] == 1
    assert incidents_payload['summary']['failed_canon_job_count'] == 1


def test_feedback_validation_errors(client):
    response = client.post('/api/feedback/coherence', data='not-json', content_type='text/plain')
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'

    response = client.post('/api/feedback/coherence', json={'session_id': 1})
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'

    response = client.post('/api/feedback/coherence', json={'session_id': 1, 'coherence_score': 7})
    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'validation_error'
