"""beta runtime tables

Revision ID: 0002_beta_runtime
Revises: 0001_initial_core
Create Date: 2026-02-05 22:03:19.791123

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002_beta_runtime'
down_revision = '0001_initial_core'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('session_log_entries', sa.Column('metadata_json', sa.Text(), nullable=True))

    op.create_table(
        'dm_turns',
        sa.Column('turn_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('player_input', sa.Text(), nullable=False),
        sa.Column('dm_output', sa.Text(), nullable=True),
        sa.Column('requires_roll', sa.Boolean(), nullable=True),
        sa.Column('rule_type', sa.String(), nullable=True),
        sa.Column('rules_hint', sa.Text(), nullable=True),
        sa.Column('context_version', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('llm_provider', sa.String(), nullable=True),
        sa.Column('llm_model', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_dm_turns_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['player_id'], ['players.player_id'], name=op.f('fk_dm_turns_player_id_players')),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_dm_turns_session_id_sessions')),
        sa.PrimaryKeyConstraint('turn_id', name=op.f('pk_dm_turns')),
    )
    op.create_index(op.f('ix_dm_turns_campaign_id'), 'dm_turns', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_dm_turns_player_id'), 'dm_turns', ['player_id'], unique=False)
    op.create_index(op.f('ix_dm_turns_session_id'), 'dm_turns', ['session_id'], unique=False)

    op.create_table(
        'session_states',
        sa.Column('state_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('rolling_summary', sa.Text(), nullable=True),
        sa.Column('current_location', sa.Text(), nullable=True),
        sa.Column('current_quest', sa.Text(), nullable=True),
        sa.Column('active_segments', sa.Text(), nullable=True),
        sa.Column('memory_snippets', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_session_states_session_id_sessions')),
        sa.PrimaryKeyConstraint('state_id', name=op.f('pk_session_states')),
    )
    op.create_index(op.f('ix_session_states_session_id'), 'session_states', ['session_id'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_session_states_session_id'), table_name='session_states')
    op.drop_table('session_states')

    op.drop_index(op.f('ix_dm_turns_session_id'), table_name='dm_turns')
    op.drop_index(op.f('ix_dm_turns_player_id'), table_name='dm_turns')
    op.drop_index(op.f('ix_dm_turns_campaign_id'), table_name='dm_turns')
    op.drop_table('dm_turns')

    op.drop_column('session_log_entries', 'metadata_json')
