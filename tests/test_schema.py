from __future__ import annotations

from sqlalchemy import inspect

from aidm_server.database import db


def test_schema_contains_new_beta_tables(app):
    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

    assert 'dm_turns' in tables
    assert 'session_states' in tables
    assert 'dm_coherence_feedback' in tables
    assert 'session_log_entries' in tables
    assert 'story_entities' in tables
    assert 'story_facts' in tables
    assert 'story_threads' in tables
    assert 'turn_canon_updates' in tables
    assert 'turn_events' in tables


def test_schema_create_all_idempotent(app):
    with app.app_context():
        db.create_all()
        db.create_all()
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

    assert 'worlds' in tables
    assert 'campaigns' in tables
    assert 'players' in tables
