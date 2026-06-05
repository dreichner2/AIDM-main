"""turn confidence and feedback

Revision ID: 0003_turn_confidence_feedback
Revises: 0002_beta_runtime
Create Date: 2026-02-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_turn_confidence_feedback'
down_revision = '0002_beta_runtime'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('dm_turns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confidence', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('roll_value', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('outcome_status', sa.String(), nullable=True))

    op.create_table(
        'dm_coherence_feedback',
        sa.Column('feedback_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('turn_id', sa.Integer(), nullable=True),
        sa.Column('coherence_score', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['session_id'],
            ['sessions.session_id'],
            name=op.f('fk_dm_coherence_feedback_session_id_sessions'),
        ),
        sa.ForeignKeyConstraint(
            ['turn_id'],
            ['dm_turns.turn_id'],
            name=op.f('fk_dm_coherence_feedback_turn_id_dm_turns'),
        ),
        sa.PrimaryKeyConstraint('feedback_id', name=op.f('pk_dm_coherence_feedback')),
    )
    op.create_index(op.f('ix_dm_coherence_feedback_session_id'), 'dm_coherence_feedback', ['session_id'], unique=False)
    op.create_index(op.f('ix_dm_coherence_feedback_turn_id'), 'dm_coherence_feedback', ['turn_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_dm_coherence_feedback_turn_id'), table_name='dm_coherence_feedback')
    op.drop_index(op.f('ix_dm_coherence_feedback_session_id'), table_name='dm_coherence_feedback')
    op.drop_table('dm_coherence_feedback')

    with op.batch_alter_table('dm_turns', schema=None) as batch_op:
        batch_op.drop_column('outcome_status')
        batch_op.drop_column('roll_value')
        batch_op.drop_column('confidence')
