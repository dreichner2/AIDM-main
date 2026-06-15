"""session state mutation audits

Revision ID: 0025_session_state_mutation_audits
Revises: 0024_turn_feedback_incident_metadata
Create Date: 2026-06-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '0025_session_state_mutation_audits'
down_revision = '0024_turn_feedback_incident_metadata'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name):
    return {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    if 'session_state_mutation_audits' not in _tables():
        op.create_table(
            'session_state_mutation_audits',
            sa.Column('mutation_audit_id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=False),
            sa.Column('campaign_id', sa.Integer(), nullable=False),
            sa.Column('source', sa.String(length=120), nullable=False),
            sa.Column('actor', sa.String(length=160), nullable=False),
            sa.Column('actor_account_id', sa.Integer(), nullable=True),
            sa.Column('actor_role', sa.String(length=32), nullable=False),
            sa.Column('previous_revision', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('state_revision', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('applied_change_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('rejected_change_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('applied_change_ids_json', sa.Text(), nullable=False),
            sa.Column('diff_json', sa.Text(), nullable=False),
            sa.Column('metadata_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ['actor_account_id'],
                ['accounts.account_id'],
                name=op.f('fk_session_state_mutation_audits_actor_account_id_accounts'),
                ondelete='SET NULL',
            ),
            sa.ForeignKeyConstraint(
                ['campaign_id'],
                ['campaigns.campaign_id'],
                name=op.f('fk_session_state_mutation_audits_campaign_id_campaigns'),
                ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['session_id'],
                ['sessions.session_id'],
                name=op.f('fk_session_state_mutation_audits_session_id_sessions'),
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('mutation_audit_id', name=op.f('pk_session_state_mutation_audits')),
        )

    indexes = _index_names('session_state_mutation_audits')
    index_specs = {
        'ix_session_state_mutation_audits_actor_account_id': ['actor_account_id'],
        'ix_session_state_mutation_audits_campaign_id': ['campaign_id'],
        'ix_session_state_mutation_audits_created_at': ['created_at'],
        'ix_session_state_mutation_audits_session_id': ['session_id'],
        'ix_session_state_mutation_audits_source': ['source'],
        'ix_state_mutation_audits_campaign_created': ['campaign_id', 'created_at'],
        'ix_state_mutation_audits_session_created': ['session_id', 'created_at'],
        'ix_state_mutation_audits_source_created': ['source', 'created_at'],
    }
    for index_name, columns in index_specs.items():
        if index_name not in indexes:
            op.create_index(index_name, 'session_state_mutation_audits', columns, unique=False)


def downgrade():
    if 'session_state_mutation_audits' in _tables():
        op.drop_table('session_state_mutation_audits')
