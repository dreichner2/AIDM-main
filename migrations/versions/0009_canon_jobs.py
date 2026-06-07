"""durable canon extraction jobs

Revision ID: 0009_canon_jobs
Revises: 0008_session_delete_semantics
Create Date: 2026-06-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009_canon_jobs'
down_revision = '0008_session_delete_semantics'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'canon_jobs',
        sa.Column('job_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('turn_id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('speaking_player_name', sa.String(), nullable=True),
        sa.Column('triggered_segments_json', sa.Text(), nullable=True),
        sa.Column('error_text', sa.Text(), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_canon_jobs_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_canon_jobs_session_id_sessions'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['turn_id'], ['dm_turns.turn_id'], name=op.f('fk_canon_jobs_turn_id_dm_turns'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id', name=op.f('pk_canon_jobs')),
        sa.UniqueConstraint('turn_id', name=op.f('uq_canon_jobs_turn_id')),
    )
    op.create_index(op.f('ix_canon_jobs_campaign_id'), 'canon_jobs', ['campaign_id'], unique=False)
    op.create_index('ix_canon_jobs_campaign_status_created_at', 'canon_jobs', ['campaign_id', 'status', 'created_at'], unique=False)
    op.create_index(op.f('ix_canon_jobs_session_id'), 'canon_jobs', ['session_id'], unique=False)
    op.create_index(op.f('ix_canon_jobs_status'), 'canon_jobs', ['status'], unique=False)
    op.create_index('ix_canon_jobs_status_next_run_at', 'canon_jobs', ['status', 'next_run_at'], unique=False)
    op.create_index(op.f('ix_canon_jobs_turn_id'), 'canon_jobs', ['turn_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_canon_jobs_turn_id'), table_name='canon_jobs')
    op.drop_index('ix_canon_jobs_status_next_run_at', table_name='canon_jobs')
    op.drop_index(op.f('ix_canon_jobs_status'), table_name='canon_jobs')
    op.drop_index(op.f('ix_canon_jobs_session_id'), table_name='canon_jobs')
    op.drop_index('ix_canon_jobs_campaign_status_created_at', table_name='canon_jobs')
    op.drop_index(op.f('ix_canon_jobs_campaign_id'), table_name='canon_jobs')
    op.drop_table('canon_jobs')
