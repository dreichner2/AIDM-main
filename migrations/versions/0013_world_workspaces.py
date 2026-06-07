"""world workspaces

Revision ID: 0013_world_workspaces
Revises: 0012_campaign_workspaces
Create Date: 2026-06-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0013_world_workspaces'
down_revision = '0012_campaign_workspaces'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('worlds', schema=None) as batch_op:
        batch_op.add_column(sa.Column('workspace_id', sa.String(length=80), server_default='owner', nullable=False))
    op.create_index('ix_worlds_workspace_id', 'worlds', ['workspace_id'], unique=False)
    op.create_index(
        'ix_worlds_workspace_created_at',
        'worlds',
        ['workspace_id', 'created_at'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_worlds_workspace_created_at', table_name='worlds')
    op.drop_index('ix_worlds_workspace_id', table_name='worlds')
    with op.batch_alter_table('worlds', schema=None) as batch_op:
        batch_op.drop_column('workspace_id')
