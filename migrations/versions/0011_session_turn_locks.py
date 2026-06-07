"""session turn locks

Revision ID: 0011_session_turn_locks
Revises: 0010_review_addendum_hardening
Create Date: 2026-06-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011_session_turn_locks'
down_revision = '0010_review_addendum_hardening'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'session_turn_locks',
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('owner_token', sa.String(length=64), nullable=False),
        sa.Column('acquired_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['session_id'],
            ['sessions.session_id'],
            name=op.f('fk_session_turn_locks_session_id_sessions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('session_id', name=op.f('pk_session_turn_locks')),
    )
    op.create_index(
        'ix_session_turn_locks_expires_at',
        'session_turn_locks',
        ['expires_at'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_session_turn_locks_expires_at', table_name='session_turn_locks')
    op.drop_table('session_turn_locks')
