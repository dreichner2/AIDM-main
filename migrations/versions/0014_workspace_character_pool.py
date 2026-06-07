"""workspace character pool

Revision ID: 0014_workspace_character_pool
Revises: 0013_world_workspaces
Create Date: 2026-06-07 00:00:00.000000

"""

from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014_workspace_character_pool'
down_revision = '0013_world_workspaces'
branch_labels = None
depends_on = None


def _player_columns():
    return {column['name']: column for column in sa.inspect(op.get_bind()).get_columns('players')}


def _index_names(table_name):
    return {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


@contextmanager
def _sqlite_foreign_keys_disabled():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        yield
        return

    original = bind.exec_driver_sql('PRAGMA foreign_keys').scalar()
    bind.exec_driver_sql('PRAGMA foreign_keys=OFF')
    try:
        yield
    finally:
        bind.exec_driver_sql(f'PRAGMA foreign_keys={int(bool(original))}')


def upgrade():
    with _sqlite_foreign_keys_disabled():
        columns = _player_columns()
        if 'workspace_id' not in columns:
            with op.batch_alter_table('players', schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column('workspace_id', sa.String(length=80), server_default='owner', nullable=False)
                )

        op.execute(
            """
            UPDATE players
            SET workspace_id = COALESCE(
                (
                    SELECT campaigns.workspace_id
                    FROM campaigns
                    WHERE campaigns.campaign_id = players.campaign_id
                ),
                'owner'
            )
            """
        )

        columns = _player_columns()
        if columns.get('campaign_id', {}).get('nullable') is False:
            with op.batch_alter_table('players', schema=None) as batch_op:
                batch_op.alter_column(
                    'campaign_id',
                    existing_type=sa.Integer(),
                    nullable=True,
                )

    existing_indexes = _index_names('players')
    if 'ix_players_workspace_id' not in existing_indexes:
        op.create_index('ix_players_workspace_id', 'players', ['workspace_id'], unique=False)
    if 'ix_players_workspace_created_at' not in existing_indexes:
        op.create_index(
            'ix_players_workspace_created_at',
            'players',
            ['workspace_id', 'created_at'],
            unique=False,
        )


def downgrade():
    with _sqlite_foreign_keys_disabled():
        if 'workspace_id' in _player_columns():
            op.execute(
                """
                UPDATE players
                SET campaign_id = (
                    SELECT MIN(campaigns.campaign_id)
                    FROM campaigns
                    WHERE campaigns.workspace_id = players.workspace_id
                )
                WHERE campaign_id IS NULL
                """
            )
        op.execute('DELETE FROM players WHERE campaign_id IS NULL')

        existing_indexes = _index_names('players')
        if 'ix_players_workspace_created_at' in existing_indexes:
            op.drop_index('ix_players_workspace_created_at', table_name='players')
        if 'ix_players_workspace_id' in existing_indexes:
            op.drop_index('ix_players_workspace_id', table_name='players')
        columns = _player_columns()
        with op.batch_alter_table('players', schema=None) as batch_op:
            if columns.get('campaign_id', {}).get('nullable') is not False:
                batch_op.alter_column(
                    'campaign_id',
                    existing_type=sa.Integer(),
                    nullable=False,
                )
            if 'workspace_id' in columns:
                batch_op.drop_column('workspace_id')
