"""session delete foreign key semantics

Revision ID: 0008_session_delete_semantics
Revises: 0007_rate_limit_events
Create Date: 2026-06-06 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '0008_session_delete_semantics'
down_revision = '0007_rate_limit_events'
branch_labels = None
depends_on = None


def _replace_fk(
    table_name: str,
    constraint_name: str,
    local_cols: list[str],
    remote_table: str,
    remote_cols: list[str],
    *,
    ondelete: str | None,
) -> None:
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(constraint_name), type_='foreignkey')
        batch_op.create_foreign_key(
            op.f(constraint_name),
            remote_table,
            local_cols,
            remote_cols,
            ondelete=ondelete,
        )


def upgrade():
    _replace_fk(
        'player_actions',
        'fk_player_actions_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='CASCADE',
    )
    _replace_fk(
        'session_log_entries',
        'fk_session_log_entries_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='CASCADE',
    )
    _replace_fk(
        'dm_turns',
        'fk_dm_turns_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='CASCADE',
    )
    _replace_fk(
        'session_states',
        'fk_session_states_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='CASCADE',
    )
    _replace_fk(
        'dm_coherence_feedback',
        'fk_dm_coherence_feedback_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='CASCADE',
    )
    _replace_fk(
        'dm_coherence_feedback',
        'fk_dm_coherence_feedback_turn_id_dm_turns',
        ['turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'turn_events',
        'fk_turn_events_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='CASCADE',
    )
    _replace_fk(
        'turn_events',
        'fk_turn_events_turn_id_dm_turns',
        ['turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_entities',
        'fk_story_entities_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_entities',
        'fk_story_entities_first_seen_turn_id_dm_turns',
        ['first_seen_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_entities',
        'fk_story_entities_last_seen_turn_id_dm_turns',
        ['last_seen_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_facts',
        'fk_story_facts_source_turn_id_dm_turns',
        ['source_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_threads',
        'fk_story_threads_origin_turn_id_dm_turns',
        ['origin_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_threads',
        'fk_story_threads_last_touched_turn_id_dm_turns',
        ['last_touched_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'story_threads',
        'fk_story_threads_resolved_turn_id_dm_turns',
        ['resolved_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='SET NULL',
    )
    _replace_fk(
        'turn_canon_updates',
        'fk_turn_canon_updates_turn_id_dm_turns',
        ['turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete='CASCADE',
    )


def downgrade():
    _replace_fk(
        'turn_canon_updates',
        'fk_turn_canon_updates_turn_id_dm_turns',
        ['turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_threads',
        'fk_story_threads_resolved_turn_id_dm_turns',
        ['resolved_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_threads',
        'fk_story_threads_last_touched_turn_id_dm_turns',
        ['last_touched_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_threads',
        'fk_story_threads_origin_turn_id_dm_turns',
        ['origin_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_facts',
        'fk_story_facts_source_turn_id_dm_turns',
        ['source_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_entities',
        'fk_story_entities_last_seen_turn_id_dm_turns',
        ['last_seen_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_entities',
        'fk_story_entities_first_seen_turn_id_dm_turns',
        ['first_seen_turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'story_entities',
        'fk_story_entities_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
    _replace_fk(
        'turn_events',
        'fk_turn_events_turn_id_dm_turns',
        ['turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'turn_events',
        'fk_turn_events_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
    _replace_fk(
        'dm_coherence_feedback',
        'fk_dm_coherence_feedback_turn_id_dm_turns',
        ['turn_id'],
        'dm_turns',
        ['turn_id'],
        ondelete=None,
    )
    _replace_fk(
        'dm_coherence_feedback',
        'fk_dm_coherence_feedback_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
    _replace_fk(
        'session_states',
        'fk_session_states_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
    _replace_fk(
        'dm_turns',
        'fk_dm_turns_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
    _replace_fk(
        'session_log_entries',
        'fk_session_log_entries_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
    _replace_fk(
        'player_actions',
        'fk_player_actions_session_id_sessions',
        ['session_id'],
        'sessions',
        ['session_id'],
        ondelete=None,
    )
