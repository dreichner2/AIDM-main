"""rate limit events

Revision ID: 0007_rate_limit_events
Revises: 0006_metadata_status_and_indexes
Create Date: 2026-06-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007_rate_limit_events'
down_revision = '0006_metadata_status_and_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rate_limit_events',
        sa.Column('event_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('bucket_key', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('event_id', name=op.f('pk_rate_limit_events')),
    )
    op.create_index(
        'ix_rate_limit_events_bucket_created_at',
        'rate_limit_events',
        ['bucket_key', 'created_at'],
        unique=False,
    )
    op.create_index(
        op.f('ix_rate_limit_events_created_at'),
        'rate_limit_events',
        ['created_at'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_rate_limit_events_created_at'), table_name='rate_limit_events')
    op.drop_index('ix_rate_limit_events_bucket_created_at', table_name='rate_limit_events')
    op.drop_table('rate_limit_events')
