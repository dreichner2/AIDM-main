"""initial core schema

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-02-05 22:03:19.357841

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001_initial_core'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'worlds',
        sa.Column('world_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('world_id', name=op.f('pk_worlds')),
    )

    op.create_table(
        'campaigns',
        sa.Column('campaign_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('world_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('current_quest', sa.String(), nullable=True),
        sa.Column('plot_points', sa.Text(), nullable=True),
        sa.Column('active_npcs', sa.Text(), nullable=True),
        sa.Column('location', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.world_id'], name=op.f('fk_campaigns_world_id_worlds')),
        sa.PrimaryKeyConstraint('campaign_id', name=op.f('pk_campaigns')),
    )

    op.create_table(
        'maps',
        sa.Column('map_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('world_id', sa.Integer(), nullable=True),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('map_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_maps_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.world_id'], name=op.f('fk_maps_world_id_worlds')),
        sa.PrimaryKeyConstraint('map_id', name=op.f('pk_maps')),
    )

    op.create_table(
        'npcs',
        sa.Column('npc_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('world_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=True),
        sa.Column('backstory', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.world_id'], name=op.f('fk_npcs_world_id_worlds')),
        sa.PrimaryKeyConstraint('npc_id', name=op.f('pk_npcs')),
    )

    op.create_table(
        'players',
        sa.Column('player_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('character_name', sa.String(), nullable=False),
        sa.Column('race', sa.String(), nullable=True),
        sa.Column('class_', sa.String(), nullable=True),
        sa.Column('level', sa.Integer(), nullable=True),
        sa.Column('stats', sa.Text(), nullable=True),
        sa.Column('inventory', sa.Text(), nullable=True),
        sa.Column('character_sheet', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_players_campaign_id_campaigns')),
        sa.PrimaryKeyConstraint('player_id', name=op.f('pk_players')),
    )

    op.create_table(
        'sessions',
        sa.Column('session_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('state_snapshot', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_sessions_campaign_id_campaigns')),
        sa.PrimaryKeyConstraint('session_id', name=op.f('pk_sessions')),
    )

    op.create_table(
        'campaign_segments',
        sa.Column('segment_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_condition', sa.Text(), nullable=True),
        sa.Column('tags', sa.Text(), nullable=True),
        sa.Column('is_triggered', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_campaign_segments_campaign_id_campaigns')),
        sa.PrimaryKeyConstraint('segment_id', name=op.f('pk_campaign_segments')),
    )

    op.create_table(
        'player_actions',
        sa.Column('action_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('action_text', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['player_id'], ['players.player_id'], name=op.f('fk_player_actions_player_id_players')),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_player_actions_session_id_sessions')),
        sa.PrimaryKeyConstraint('action_id', name=op.f('pk_player_actions')),
    )

    op.create_table(
        'session_log_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_session_log_entries_session_id_sessions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_session_log_entries')),
    )

    op.create_table(
        'story_events',
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('importance', sa.Integer(), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_story_events_campaign_id_campaigns')),
        sa.PrimaryKeyConstraint('event_id', name=op.f('pk_story_events')),
    )


def downgrade():
    op.drop_table('story_events')
    op.drop_table('session_log_entries')
    op.drop_table('player_actions')
    op.drop_table('campaign_segments')
    op.drop_table('sessions')
    op.drop_table('players')
    op.drop_table('npcs')
    op.drop_table('maps')
    op.drop_table('campaigns')
    op.drop_table('worlds')
