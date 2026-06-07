"""campaign workspaces

Revision ID: 0012_campaign_workspaces
Revises: 0011_session_turn_locks
Create Date: 2026-06-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0012_campaign_workspaces'
down_revision = '0011_session_turn_locks'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('workspace_id', sa.String(length=80), server_default='owner', nullable=False))
    op.create_index('ix_campaigns_workspace_id', 'campaigns', ['workspace_id'], unique=False)
    op.create_index(
        'ix_campaigns_workspace_status_updated',
        'campaigns',
        ['workspace_id', 'status', 'updated_at'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_campaigns_workspace_status_updated', table_name='campaigns')
    op.drop_index('ix_campaigns_workspace_id', table_name='campaigns')
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('workspace_id')
