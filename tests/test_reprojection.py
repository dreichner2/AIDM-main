from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from aidm_server.database import db
from aidm_server.models import PlayerAction, SessionLogEntry, SessionState, StoryFact, StoryThread
from aidm_server.reprojection import ProjectionRepairError, repair_session_projections
from aidm_server.turn_events import DM_RESPONSE_EVENT, PLAYER_MESSAGE_EVENT, record_turn_event
from tests.helpers import seed_world_campaign_player_session


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_repair_session_projections_rebuilds_legacy_rows_from_turn_events(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        record_turn_event(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            player_id=ids['player_id'],
            event_type=PLAYER_MESSAGE_EVENT,
            payload={'speaker': 'Seraphina', 'message': 'I open the ash gate.'},
            project_legacy=False,
        )
        record_turn_event(
            session_id=ids['session_id'],
            campaign_id=ids['campaign_id'],
            event_type=DM_RESPONSE_EVENT,
            payload={'message': 'The gate groans open.'},
            project_legacy=False,
        )
        db.session.add(SessionLogEntry(session_id=ids['session_id'], message='stale log', entry_type='dm'))
        db.session.add(
            PlayerAction(
                session_id=ids['session_id'],
                player_id=ids['player_id'],
                action_text='stale action',
            )
        )
        db.session.commit()

        result = repair_session_projections(ids['session_id'])
        db.session.commit()

        assert result['legacy_projections']['events_replayed'] == 2
        assert result['legacy_projections']['deleted'] == {'player_actions': 1, 'session_log_entries': 1}
        assert result['legacy_projections']['rebuilt'] == {'player_actions': 1, 'session_log_entries': 2}

        log_entries = (
            SessionLogEntry.query.filter_by(session_id=ids['session_id'])
            .order_by(SessionLogEntry.timestamp.asc(), SessionLogEntry.id.asc())
            .all()
        )
        actions = PlayerAction.query.filter_by(session_id=ids['session_id']).all()
        assert [entry.message for entry in log_entries] == ['Seraphina: I open the ash gate.', 'DM: The gate groans open.']
        assert [action.action_text for action in actions] == ['I open the ash gate.']

        second_result = repair_session_projections(ids['session_id'])
        db.session.commit()
        assert second_result['legacy_projections']['deleted'] == {'player_actions': 1, 'session_log_entries': 2}
        assert SessionLogEntry.query.filter_by(session_id=ids['session_id']).count() == 2
        assert PlayerAction.query.filter_by(session_id=ids['session_id']).count() == 1


def test_repair_session_projections_refreshes_session_state_from_canon(app):
    ids = seed_world_campaign_player_session(app)

    with app.app_context():
        db.session.add(
            StoryFact(
                campaign_id=ids['campaign_id'],
                predicate='current_location',
                value_text='Ash Chapel',
                fact_status='accepted',
                confidence=0.95,
            )
        )
        db.session.add(
            StoryThread(
                campaign_id=ids['campaign_id'],
                title='Seal the Ash Gate',
                summary='The gate must be sealed before dawn.',
                status='open',
                priority=5,
                source='emergent',
            )
        )
        db.session.add(
            SessionState(
                session_id=ids['session_id'],
                current_location='Wrong Place',
                current_quest='Wrong Quest',
            )
        )
        db.session.commit()

        result = repair_session_projections(ids['session_id'])
        db.session.commit()

        state = SessionState.query.filter_by(session_id=ids['session_id']).one()
        assert state.current_location == 'Ash Chapel'
        assert state.current_quest == 'Seal the Ash Gate'
        assert result['session_state']['current_location'] == 'Ash Chapel'
        assert result['session_state']['current_quest'] == 'Seal the Ash Gate'


def test_repair_session_projections_rejects_missing_session(app):
    with app.app_context():
        try:
            repair_session_projections(999999)
        except ProjectionRepairError as exc:
            assert 'Session not found' in str(exc)
        else:
            raise AssertionError('expected ProjectionRepairError')


def test_reprojection_cli_does_not_create_missing_schema_by_default(tmp_path):
    db_path = tmp_path / 'missing_schema.db'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_ROOT)
    env['AIDM_DATABASE_URI'] = f'sqlite:///{db_path}'
    env['AIDM_AUTO_CREATE_SCHEMA'] = 'false'
    env['AIDM_ENV'] = 'test'
    env['AIDM_TELEMETRY_ENABLED'] = 'false'

    result = subprocess.run(
        [sys.executable, 'scripts/reproject_session.py', '--all', '--dry-run'],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert 'no such table' in result.stderr.lower() or 'no such table' in result.stdout.lower()
