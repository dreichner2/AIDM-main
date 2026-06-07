from __future__ import annotations

from sqlalchemy import inspect

from aidm_server.database import db


def _fk_ondelete(inspector, table_name: str, constrained_column: str) -> str | None:
    for foreign_key in inspector.get_foreign_keys(table_name):
        if constrained_column in foreign_key.get('constrained_columns', []):
            return (foreign_key.get('options') or {}).get('ondelete')
    return None


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
    assert 'canon_jobs' in tables

    session_cols = {col['name'] for col in inspector.get_columns('sessions')}
    assert {'name', 'status', 'updated_at', 'deleted_at', 'client_session_id', 'archived_by_campaign_id'}.issubset(session_cols)
    campaign_cols = {col['name'] for col in inspector.get_columns('campaigns')}
    assert {'updated_at', 'status'}.issubset(campaign_cols)
    session_indexes = {index['name'] for index in inspector.get_indexes('sessions')}
    assert 'ix_sessions_campaign_id_status_updated_at' in session_indexes
    assert 'ix_sessions_archived_by_campaign_id' in session_indexes
    assert 'uq_sessions_campaign_client_session_id' in session_indexes
    map_checks = {constraint['name'] for constraint in inspector.get_check_constraints('maps')}
    assert 'ck_maps_maps_has_owner' in map_checks
    assert _fk_ondelete(inspector, 'dm_turns', 'session_id') == 'CASCADE'
    assert _fk_ondelete(inspector, 'sessions', 'archived_by_campaign_id') == 'SET NULL'
    assert _fk_ondelete(inspector, 'session_log_entries', 'session_id') == 'CASCADE'
    assert _fk_ondelete(inspector, 'session_states', 'session_id') == 'CASCADE'
    assert _fk_ondelete(inspector, 'story_entities', 'session_id') == 'SET NULL'
    assert _fk_ondelete(inspector, 'story_entities', 'first_seen_turn_id') == 'SET NULL'
    assert _fk_ondelete(inspector, 'story_facts', 'source_turn_id') == 'SET NULL'
    assert _fk_ondelete(inspector, 'story_threads', 'origin_turn_id') == 'SET NULL'
    assert _fk_ondelete(inspector, 'turn_canon_updates', 'turn_id') == 'CASCADE'
    assert _fk_ondelete(inspector, 'canon_jobs', 'turn_id') == 'CASCADE'
    assert _fk_ondelete(inspector, 'canon_jobs', 'session_id') == 'CASCADE'


def test_schema_create_all_idempotent(app):
    with app.app_context():
        db.create_all()
        db.create_all()
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

    assert 'worlds' in tables
    assert 'campaigns' in tables
    assert 'players' in tables
