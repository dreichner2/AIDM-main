"""metadata status columns and common indexes

Revision ID: 0006_metadata_status_and_indexes
Revises: 0005_turn_event_spine
Create Date: 2026-06-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006_metadata_status_and_indexes'
down_revision = '0005_turn_event_spine'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=32), nullable=True))

    with op.batch_alter_table('maps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('campaign_segments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    op.execute("UPDATE campaigns SET status = COALESCE(status, 'active'), updated_at = COALESCE(updated_at, created_at)")
    op.execute("UPDATE maps SET updated_at = COALESCE(updated_at, created_at)")
    op.execute("UPDATE players SET updated_at = COALESCE(updated_at, created_at)")
    op.execute("UPDATE sessions SET status = COALESCE(status, 'active'), updated_at = COALESCE(updated_at, created_at)")
    op.execute("UPDATE campaign_segments SET updated_at = COALESCE(updated_at, created_at)")

    op.create_index(op.f('ix_campaigns_status'), 'campaigns', ['status'], unique=False)
    op.create_index('ix_campaigns_status_created_at', 'campaigns', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_campaigns_updated_at'), 'campaigns', ['updated_at'], unique=False)
    op.create_index(op.f('ix_sessions_status'), 'sessions', ['status'], unique=False)
    op.create_index('ix_sessions_campaign_id_created_at', 'sessions', ['campaign_id', 'created_at'], unique=False)
    op.create_index(
        'ix_sessions_campaign_id_status_updated_at',
        'sessions',
        ['campaign_id', 'status', 'updated_at'],
        unique=False,
    )
    op.create_index(
        'ix_session_log_entries_session_id_timestamp_id',
        'session_log_entries',
        ['session_id', 'timestamp', 'id'],
        unique=False,
    )
    op.create_index(
        'ix_campaign_segments_campaign_id_is_triggered',
        'campaign_segments',
        ['campaign_id', 'is_triggered'],
        unique=False,
    )
    op.create_index(
        'ix_story_entities_campaign_type_status',
        'story_entities',
        ['campaign_id', 'entity_type', 'status'],
        unique=False,
    )
    op.create_index(
        'ix_story_facts_campaign_id_predicate',
        'story_facts',
        ['campaign_id', 'predicate'],
        unique=False,
    )
    op.create_index(
        'ix_story_facts_campaign_subject_predicate',
        'story_facts',
        ['campaign_id', 'subject_entity_id', 'predicate'],
        unique=False,
    )
    op.create_index(
        'ix_story_threads_campaign_status_updated_at',
        'story_threads',
        ['campaign_id', 'status', 'updated_at'],
        unique=False,
    )
    op.create_index(
        'ix_turn_canon_updates_campaign_status_created_at',
        'turn_canon_updates',
        ['campaign_id', 'status', 'created_at'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_turn_canon_updates_campaign_status_created_at', table_name='turn_canon_updates')
    op.drop_index('ix_story_threads_campaign_status_updated_at', table_name='story_threads')
    op.drop_index('ix_story_facts_campaign_subject_predicate', table_name='story_facts')
    op.drop_index('ix_story_facts_campaign_id_predicate', table_name='story_facts')
    op.drop_index('ix_story_entities_campaign_type_status', table_name='story_entities')
    op.drop_index('ix_campaign_segments_campaign_id_is_triggered', table_name='campaign_segments')
    op.drop_index('ix_session_log_entries_session_id_timestamp_id', table_name='session_log_entries')
    op.drop_index('ix_sessions_campaign_id_status_updated_at', table_name='sessions')
    op.drop_index('ix_sessions_campaign_id_created_at', table_name='sessions')
    op.drop_index(op.f('ix_sessions_status'), table_name='sessions')
    op.drop_index(op.f('ix_campaigns_updated_at'), table_name='campaigns')
    op.drop_index('ix_campaigns_status_created_at', table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_status'), table_name='campaigns')

    with op.batch_alter_table('campaign_segments', schema=None) as batch_op:
        batch_op.drop_column('updated_at')

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('status')
        batch_op.drop_column('name')

    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('updated_at')

    with op.batch_alter_table('maps', schema=None) as batch_op:
        batch_op.drop_column('updated_at')

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('status')
        batch_op.drop_column('updated_at')
