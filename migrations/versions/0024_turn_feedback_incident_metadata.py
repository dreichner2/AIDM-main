"""turn feedback incident metadata

Revision ID: 0024_turn_feedback_incident_metadata
Revises: 0023_campaign_segment_source_identity
Create Date: 2026-06-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '0024_turn_feedback_incident_metadata'
down_revision = '0023_campaign_segment_source_identity'
branch_labels = None
depends_on = None


def _columns(table_name):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name):
    return {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    columns = _columns('dm_coherence_feedback')
    with op.batch_alter_table('dm_coherence_feedback', schema=None) as batch_op:
        if 'feedback_type' not in columns:
            batch_op.add_column(
                sa.Column('feedback_type', sa.String(length=32), nullable=False, server_default='coherence')
            )
        if 'category' not in columns:
            batch_op.add_column(sa.Column('category', sa.String(length=64), nullable=True))
        if 'provider' not in columns:
            batch_op.add_column(sa.Column('provider', sa.String(), nullable=True))
        if 'model' not in columns:
            batch_op.add_column(sa.Column('model', sa.String(), nullable=True))
        if 'metadata_json' not in columns:
            batch_op.add_column(sa.Column('metadata_json', sa.Text(), nullable=True))

    if 'feedback_type' not in columns:
        op.execute("UPDATE dm_coherence_feedback SET feedback_type = 'coherence' WHERE feedback_type IS NULL OR feedback_type = ''")
        with op.batch_alter_table('dm_coherence_feedback', schema=None) as batch_op:
            batch_op.alter_column('feedback_type', server_default=None)

    if 'ix_dm_coherence_feedback_type_created_at' not in _index_names('dm_coherence_feedback'):
        op.create_index(
            'ix_dm_coherence_feedback_type_created_at',
            'dm_coherence_feedback',
            ['feedback_type', 'created_at'],
            unique=False,
        )


def downgrade():
    if 'ix_dm_coherence_feedback_type_created_at' in _index_names('dm_coherence_feedback'):
        op.drop_index('ix_dm_coherence_feedback_type_created_at', table_name='dm_coherence_feedback')
    columns = _columns('dm_coherence_feedback')
    with op.batch_alter_table('dm_coherence_feedback', schema=None) as batch_op:
        if 'metadata_json' in columns:
            batch_op.drop_column('metadata_json')
        if 'model' in columns:
            batch_op.drop_column('model')
        if 'provider' in columns:
            batch_op.drop_column('provider')
        if 'category' in columns:
            batch_op.drop_column('category')
        if 'feedback_type' in columns:
            batch_op.drop_column('feedback_type')
