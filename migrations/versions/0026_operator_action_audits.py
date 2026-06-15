"""operator action audits

Revision ID: 0026_operator_action_audits
Revises: 0025_session_state_mutation_audits
Create Date: 2026-06-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '0026_operator_action_audits'
down_revision = '0025_session_state_mutation_audits'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name):
    return {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    if 'operator_action_audits' not in _tables():
        op.create_table(
            'operator_action_audits',
            sa.Column('operator_audit_id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('workspace_id', sa.String(length=80), nullable=False),
            sa.Column('campaign_id', sa.Integer(), nullable=True),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('action', sa.String(length=120), nullable=False),
            sa.Column('resource_type', sa.String(length=80), nullable=False),
            sa.Column('resource_id', sa.String(length=160), nullable=True),
            sa.Column('actor', sa.String(length=160), nullable=False),
            sa.Column('actor_account_id', sa.Integer(), nullable=True),
            sa.Column('actor_role', sa.String(length=32), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='success'),
            sa.Column('details_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ['actor_account_id'],
                ['accounts.account_id'],
                name=op.f('fk_operator_action_audits_actor_account_id_accounts'),
                ondelete='SET NULL',
            ),
            sa.ForeignKeyConstraint(
                ['campaign_id'],
                ['campaigns.campaign_id'],
                name=op.f('fk_operator_action_audits_campaign_id_campaigns'),
                ondelete='SET NULL',
            ),
            sa.ForeignKeyConstraint(
                ['session_id'],
                ['sessions.session_id'],
                name=op.f('fk_operator_action_audits_session_id_sessions'),
                ondelete='SET NULL',
            ),
            sa.PrimaryKeyConstraint('operator_audit_id', name=op.f('pk_operator_action_audits')),
        )
    indexes = _index_names('operator_action_audits')
    index_specs = {
        'ix_operator_action_audits_action': ['action'],
        'ix_operator_action_audits_action_created': ['action', 'created_at'],
        'ix_operator_action_audits_actor_account_id': ['actor_account_id'],
        'ix_operator_action_audits_campaign_created': ['campaign_id', 'created_at'],
        'ix_operator_action_audits_campaign_id': ['campaign_id'],
        'ix_operator_action_audits_created_at': ['created_at'],
        'ix_operator_action_audits_session_created': ['session_id', 'created_at'],
        'ix_operator_action_audits_session_id': ['session_id'],
        'ix_operator_action_audits_workspace_created': ['workspace_id', 'created_at'],
        'ix_operator_action_audits_workspace_id': ['workspace_id'],
    }
    for index_name, columns in index_specs.items():
        if index_name not in indexes:
            op.create_index(index_name, 'operator_action_audits', columns, unique=False)


def downgrade():
    if 'operator_action_audits' in _tables():
        op.drop_table('operator_action_audits')
