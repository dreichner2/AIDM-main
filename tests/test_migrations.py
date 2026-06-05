from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from sqlalchemy import create_engine, inspect


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run_flask_db(args: list[str], env: dict):
    cmd = [sys.executable, '-m', 'flask', 'db', *args]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def _inspect_db(db_uri: str):
    engine = create_engine(db_uri)
    try:
        return inspect(engine)
    finally:
        engine.dispose()


def test_migration_chain_upgrade_and_downgrade(tmp_path):
    db_path = tmp_path / 'migration_chain.db'
    db_uri = f'sqlite:///{db_path}'

    env = os.environ.copy()
    env['FLASK_APP'] = 'aidm_server.main:create_app'
    env['PYTHONPATH'] = str(REPO_ROOT)
    env['AIDM_ENV'] = 'test'
    env['AIDM_DEBUG'] = 'false'
    env['AIDM_SOCKETIO_ASYNC_MODE'] = 'threading'
    env['AIDM_AUTO_CREATE_SCHEMA'] = 'false'
    env['AIDM_DATABASE_URI'] = db_uri
    env['AIDM_TELEMETRY_ENABLED'] = 'false'

    _run_flask_db(['upgrade', '0001_initial_core'], env)

    inspector = _inspect_db(db_uri)
    tables = set(inspector.get_table_names())
    assert 'worlds' in tables
    assert 'campaigns' in tables
    assert 'session_log_entries' in tables
    assert 'dm_turns' not in tables
    assert 'session_states' not in tables

    entry_cols_v1 = {col['name'] for col in inspector.get_columns('session_log_entries')}
    assert 'metadata_json' not in entry_cols_v1

    _run_flask_db(['upgrade', 'head'], env)

    inspector = _inspect_db(db_uri)
    tables = set(inspector.get_table_names())
    assert 'dm_turns' in tables
    assert 'session_states' in tables
    assert 'dm_coherence_feedback' in tables
    assert 'story_entities' in tables
    assert 'story_facts' in tables
    assert 'story_threads' in tables
    assert 'turn_canon_updates' in tables
    assert 'turn_events' in tables
    entry_cols_head = {col['name'] for col in inspector.get_columns('session_log_entries')}
    assert 'metadata_json' in entry_cols_head
    dm_turn_cols_head = {col['name'] for col in inspector.get_columns('dm_turns')}
    assert {'confidence', 'roll_value', 'outcome_status'}.issubset(dm_turn_cols_head)

    _run_flask_db(['downgrade', '0001_initial_core'], env)

    inspector = _inspect_db(db_uri)
    tables = set(inspector.get_table_names())
    assert 'dm_turns' not in tables
    assert 'session_states' not in tables
    assert 'dm_coherence_feedback' not in tables
    assert 'story_entities' not in tables
    assert 'story_facts' not in tables
    assert 'story_threads' not in tables
    assert 'turn_canon_updates' not in tables
    assert 'turn_events' not in tables
    entry_cols_after_down = {col['name'] for col in inspector.get_columns('session_log_entries')}
    assert 'metadata_json' not in entry_cols_after_down

    _run_flask_db(['upgrade', 'head'], env)

    inspector = _inspect_db(db_uri)
    tables = set(inspector.get_table_names())
    assert 'dm_turns' in tables
    assert 'session_states' in tables
    assert 'dm_coherence_feedback' in tables
    assert 'story_entities' in tables
    assert 'story_facts' in tables
    assert 'story_threads' in tables
    assert 'turn_canon_updates' in tables
    assert 'turn_events' in tables


def test_migration_chain_downgrade_to_base_and_reupgrade(tmp_path):
    db_path = tmp_path / 'migration_chain_full_reset.db'
    db_uri = f'sqlite:///{db_path}'

    env = os.environ.copy()
    env['FLASK_APP'] = 'aidm_server.main:create_app'
    env['PYTHONPATH'] = str(REPO_ROOT)
    env['AIDM_ENV'] = 'test'
    env['AIDM_DEBUG'] = 'false'
    env['AIDM_SOCKETIO_ASYNC_MODE'] = 'threading'
    env['AIDM_AUTO_CREATE_SCHEMA'] = 'false'
    env['AIDM_DATABASE_URI'] = db_uri
    env['AIDM_TELEMETRY_ENABLED'] = 'false'

    _run_flask_db(['upgrade', 'head'], env)
    _run_flask_db(['downgrade', 'base'], env)

    inspector = _inspect_db(db_uri)
    tables = set(inspector.get_table_names())
    assert tables == {'alembic_version'}

    _run_flask_db(['upgrade', 'head'], env)
    inspector = _inspect_db(db_uri)
    tables = set(inspector.get_table_names())
    assert 'dm_turns' in tables
    assert 'session_states' in tables
    assert 'dm_coherence_feedback' in tables
    assert 'story_entities' in tables
    assert 'story_facts' in tables
    assert 'story_threads' in tables
    assert 'turn_canon_updates' in tables
    assert 'turn_events' in tables
