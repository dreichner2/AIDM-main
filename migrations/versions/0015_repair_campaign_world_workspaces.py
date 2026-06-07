"""repair campaign world workspaces

Revision ID: 0015_repair_campaign_world_workspaces
Revises: 0014_workspace_character_pool
Create Date: 2026-06-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0015_repair_campaign_world_workspaces'
down_revision = '0014_workspace_character_pool'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                campaigns.campaign_id,
                COALESCE(campaigns.workspace_id, 'owner') AS campaign_workspace_id,
                campaigns.title AS campaign_title,
                worlds.name AS world_name,
                worlds.description AS world_description,
                worlds.created_at AS world_created_at
            FROM campaigns
            LEFT JOIN worlds ON worlds.world_id = campaigns.world_id
            WHERE worlds.world_id IS NULL
               OR COALESCE(worlds.workspace_id, 'owner') != COALESCE(campaigns.workspace_id, 'owner')
            ORDER BY campaigns.campaign_id
            """
        )
    ).mappings().all()

    for row in rows:
        workspace_id = row['campaign_workspace_id'] or 'owner'
        world_name = row['world_name'] or f"{row['campaign_title']} World"
        world_id = bind.execute(
            sa.text(
                """
                SELECT world_id
                FROM worlds
                WHERE workspace_id = :workspace_id
                  AND name = :name
                ORDER BY world_id ASC
                LIMIT 1
                """
            ),
            {'workspace_id': workspace_id, 'name': world_name},
        ).scalar()

        if world_id is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO worlds (workspace_id, name, description, created_at)
                    VALUES (:workspace_id, :name, :description, COALESCE(:created_at, CURRENT_TIMESTAMP))
                    """
                ),
                {
                    'workspace_id': workspace_id,
                    'name': world_name,
                    'description': row['world_description'],
                    'created_at': row['world_created_at'],
                },
            )
            world_id = bind.execute(
                sa.text(
                    """
                    SELECT world_id
                    FROM worlds
                    WHERE workspace_id = :workspace_id
                      AND name = :name
                    ORDER BY world_id DESC
                    LIMIT 1
                    """
                ),
                {'workspace_id': workspace_id, 'name': world_name},
            ).scalar()

        bind.execute(
            sa.text(
                """
                UPDATE campaigns
                SET world_id = :world_id
                WHERE campaign_id = :campaign_id
                """
            ),
            {'world_id': world_id, 'campaign_id': row['campaign_id']},
        )


def downgrade():
    pass
