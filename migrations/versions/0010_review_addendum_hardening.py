"""review addendum hardening

Revision ID: 0010_review_addendum_hardening
Revises: 0009_canon_jobs
Create Date: 2026-06-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010_review_addendum_hardening'
down_revision = '0009_canon_jobs'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_session_id', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('archived_by_campaign_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f('fk_sessions_archived_by_campaign_id_campaigns'),
            'campaigns',
            ['archived_by_campaign_id'],
            ['campaign_id'],
            ondelete='SET NULL',
        )
    op.create_index(
        'ix_sessions_archived_by_campaign_id',
        'sessions',
        ['archived_by_campaign_id'],
        unique=False,
    )
    op.create_index(
        'uq_sessions_campaign_client_session_id',
        'sessions',
        ['campaign_id', 'client_session_id'],
        unique=True,
        sqlite_where=sa.text('client_session_id IS NOT NULL'),
        postgresql_where=sa.text('client_session_id IS NOT NULL'),
    )

    with op.batch_alter_table('maps', schema=None) as batch_op:
        batch_op.create_check_constraint(
            op.f('ck_maps_maps_has_owner'),
            'world_id IS NOT NULL OR campaign_id IS NOT NULL',
        )


def downgrade():
    with op.batch_alter_table('maps', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_maps_maps_has_owner'), type_='check')

    op.drop_index('uq_sessions_campaign_client_session_id', table_name='sessions')
    op.drop_index('ix_sessions_archived_by_campaign_id', table_name='sessions')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('fk_sessions_archived_by_campaign_id_campaigns'), type_='foreignkey')
        batch_op.drop_column('archived_by_campaign_id')
        batch_op.drop_column('client_session_id')
