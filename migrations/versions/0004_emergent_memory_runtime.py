"""emergent memory runtime tables

Revision ID: 0004_emergent_memory_runtime
Revises: 0003_turn_confidence_feedback
Create Date: 2026-03-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_emergent_memory_runtime'
down_revision = '0003_turn_confidence_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'story_entities',
        sa.Column('entity_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('canonical_name', sa.String(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('aliases_json', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('first_seen_turn_id', sa.Integer(), nullable=True),
        sa.Column('last_seen_turn_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_story_entities_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['first_seen_turn_id'], ['dm_turns.turn_id'], name=op.f('fk_story_entities_first_seen_turn_id_dm_turns')),
        sa.ForeignKeyConstraint(['last_seen_turn_id'], ['dm_turns.turn_id'], name=op.f('fk_story_entities_last_seen_turn_id_dm_turns')),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], name=op.f('fk_story_entities_session_id_sessions')),
        sa.PrimaryKeyConstraint('entity_id', name=op.f('pk_story_entities')),
    )
    op.create_index(op.f('ix_story_entities_campaign_id'), 'story_entities', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_story_entities_entity_type'), 'story_entities', ['entity_type'], unique=False)
    op.create_index(op.f('ix_story_entities_first_seen_turn_id'), 'story_entities', ['first_seen_turn_id'], unique=False)
    op.create_index(op.f('ix_story_entities_last_seen_turn_id'), 'story_entities', ['last_seen_turn_id'], unique=False)
    op.create_index(op.f('ix_story_entities_session_id'), 'story_entities', ['session_id'], unique=False)

    op.create_table(
        'story_facts',
        sa.Column('fact_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('subject_entity_id', sa.Integer(), nullable=True),
        sa.Column('predicate', sa.String(), nullable=False),
        sa.Column('object_entity_id', sa.Integer(), nullable=True),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('value_json', sa.Text(), nullable=True),
        sa.Column('fact_status', sa.String(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('source_turn_id', sa.Integer(), nullable=True),
        sa.Column('supersedes_fact_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_story_facts_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['object_entity_id'], ['story_entities.entity_id'], name=op.f('fk_story_facts_object_entity_id_story_entities')),
        sa.ForeignKeyConstraint(['source_turn_id'], ['dm_turns.turn_id'], name=op.f('fk_story_facts_source_turn_id_dm_turns')),
        sa.ForeignKeyConstraint(['subject_entity_id'], ['story_entities.entity_id'], name=op.f('fk_story_facts_subject_entity_id_story_entities')),
        sa.ForeignKeyConstraint(['supersedes_fact_id'], ['story_facts.fact_id'], name=op.f('fk_story_facts_supersedes_fact_id_story_facts')),
        sa.PrimaryKeyConstraint('fact_id', name=op.f('pk_story_facts')),
    )
    op.create_index(op.f('ix_story_facts_campaign_id'), 'story_facts', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_story_facts_object_entity_id'), 'story_facts', ['object_entity_id'], unique=False)
    op.create_index(op.f('ix_story_facts_predicate'), 'story_facts', ['predicate'], unique=False)
    op.create_index(op.f('ix_story_facts_source_turn_id'), 'story_facts', ['source_turn_id'], unique=False)
    op.create_index(op.f('ix_story_facts_subject_entity_id'), 'story_facts', ['subject_entity_id'], unique=False)
    op.create_index(op.f('ix_story_facts_supersedes_fact_id'), 'story_facts', ['supersedes_fact_id'], unique=False)

    op.create_table(
        'story_threads',
        sa.Column('thread_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('origin_turn_id', sa.Integer(), nullable=True),
        sa.Column('last_touched_turn_id', sa.Integer(), nullable=True),
        sa.Column('resolved_turn_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_story_threads_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['last_touched_turn_id'], ['dm_turns.turn_id'], name=op.f('fk_story_threads_last_touched_turn_id_dm_turns')),
        sa.ForeignKeyConstraint(['origin_turn_id'], ['dm_turns.turn_id'], name=op.f('fk_story_threads_origin_turn_id_dm_turns')),
        sa.ForeignKeyConstraint(['resolved_turn_id'], ['dm_turns.turn_id'], name=op.f('fk_story_threads_resolved_turn_id_dm_turns')),
        sa.PrimaryKeyConstraint('thread_id', name=op.f('pk_story_threads')),
    )
    op.create_index(op.f('ix_story_threads_campaign_id'), 'story_threads', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_story_threads_last_touched_turn_id'), 'story_threads', ['last_touched_turn_id'], unique=False)
    op.create_index(op.f('ix_story_threads_origin_turn_id'), 'story_threads', ['origin_turn_id'], unique=False)
    op.create_index(op.f('ix_story_threads_resolved_turn_id'), 'story_threads', ['resolved_turn_id'], unique=False)
    op.create_index(op.f('ix_story_threads_status'), 'story_threads', ['status'], unique=False)

    op.create_table(
        'turn_canon_updates',
        sa.Column('update_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('turn_id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('raw_patch_json', sa.Text(), nullable=True),
        sa.Column('applied_patch_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('extractor_model', sa.String(), nullable=True),
        sa.Column('error_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.campaign_id'], name=op.f('fk_turn_canon_updates_campaign_id_campaigns')),
        sa.ForeignKeyConstraint(['turn_id'], ['dm_turns.turn_id'], name=op.f('fk_turn_canon_updates_turn_id_dm_turns')),
        sa.PrimaryKeyConstraint('update_id', name=op.f('pk_turn_canon_updates')),
    )
    op.create_index(op.f('ix_turn_canon_updates_campaign_id'), 'turn_canon_updates', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_turn_canon_updates_status'), 'turn_canon_updates', ['status'], unique=False)
    op.create_index(op.f('ix_turn_canon_updates_turn_id'), 'turn_canon_updates', ['turn_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_turn_canon_updates_turn_id'), table_name='turn_canon_updates')
    op.drop_index(op.f('ix_turn_canon_updates_status'), table_name='turn_canon_updates')
    op.drop_index(op.f('ix_turn_canon_updates_campaign_id'), table_name='turn_canon_updates')
    op.drop_table('turn_canon_updates')

    op.drop_index(op.f('ix_story_threads_status'), table_name='story_threads')
    op.drop_index(op.f('ix_story_threads_resolved_turn_id'), table_name='story_threads')
    op.drop_index(op.f('ix_story_threads_origin_turn_id'), table_name='story_threads')
    op.drop_index(op.f('ix_story_threads_last_touched_turn_id'), table_name='story_threads')
    op.drop_index(op.f('ix_story_threads_campaign_id'), table_name='story_threads')
    op.drop_table('story_threads')

    op.drop_index(op.f('ix_story_facts_supersedes_fact_id'), table_name='story_facts')
    op.drop_index(op.f('ix_story_facts_subject_entity_id'), table_name='story_facts')
    op.drop_index(op.f('ix_story_facts_source_turn_id'), table_name='story_facts')
    op.drop_index(op.f('ix_story_facts_predicate'), table_name='story_facts')
    op.drop_index(op.f('ix_story_facts_object_entity_id'), table_name='story_facts')
    op.drop_index(op.f('ix_story_facts_campaign_id'), table_name='story_facts')
    op.drop_table('story_facts')

    op.drop_index(op.f('ix_story_entities_session_id'), table_name='story_entities')
    op.drop_index(op.f('ix_story_entities_last_seen_turn_id'), table_name='story_entities')
    op.drop_index(op.f('ix_story_entities_first_seen_turn_id'), table_name='story_entities')
    op.drop_index(op.f('ix_story_entities_entity_type'), table_name='story_entities')
    op.drop_index(op.f('ix_story_entities_campaign_id'), table_name='story_entities')
    op.drop_table('story_entities')
