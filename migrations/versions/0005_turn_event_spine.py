"""append-only turn event spine

Revision ID: 0005_turn_event_spine
Revises: 0004_emergent_memory_runtime
Create Date: 2026-03-09 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_turn_event_spine'
down_revision = '0004_emergent_memory_runtime'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'turn_events',
        sa.Column('event_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('turn_id', sa.Integer(), nullable=True),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_turn_events_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['player_id'], ['players.player_id'], name=op.f('fk_turn_events_player_id_players')),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_turn_events_session_id_sessions')),
        sa.ForeignKeyConstraint(['turn_id'], ['dm_turns.turn_id'], name=op.f('fk_turn_events_turn_id_dm_turns')),
        sa.PrimaryKeyConstraint('event_id', name=op.f('pk_turn_events')),
    )
    op.create_index(op.f('ix_turn_events_campaign_id'), 'turn_events', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_turn_events_created_at'), 'turn_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_turn_events_event_type'), 'turn_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_turn_events_player_id'), 'turn_events', ['player_id'], unique=False)
    op.create_index(op.f('ix_turn_events_session_id'), 'turn_events', ['session_id'], unique=False)
    op.create_index(op.f('ix_turn_events_turn_id'), 'turn_events', ['turn_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_turn_events_turn_id'), table_name='turn_events')
    op.drop_index(op.f('ix_turn_events_session_id'), table_name='turn_events')
    op.drop_index(op.f('ix_turn_events_player_id'), table_name='turn_events')
    op.drop_index(op.f('ix_turn_events_event_type'), table_name='turn_events')
    op.drop_index(op.f('ix_turn_events_created_at'), table_name='turn_events')
    op.drop_index(op.f('ix_turn_events_campaign_id'), table_name='turn_events')
    op.drop_table('turn_events')
