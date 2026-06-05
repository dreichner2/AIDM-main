from __future__ import annotations

import json

from aidm_server.database import db
from aidm_server.time_utils import utc_now


class World(db.Model):
    __tablename__ = 'worlds'

    world_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=utc_now)


class Campaign(db.Model):
    __tablename__ = 'campaigns'

    campaign_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    world_id = db.Column(db.Integer, db.ForeignKey('worlds.world_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)
    current_quest = db.Column(db.String, nullable=True)
    plot_points = db.Column(db.Text)
    active_npcs = db.Column(db.Text)
    location = db.Column(db.Text)

    world = db.relationship('World', backref='campaigns')


class Map(db.Model):
    __tablename__ = 'maps'

    map_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    world_id = db.Column(db.Integer, db.ForeignKey('worlds.world_id'), nullable=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=True)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.Text)
    map_data = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    world = db.relationship('World', backref='maps')
    campaign = db.relationship('Campaign', backref='maps')


class Player(db.Model):
    __tablename__ = 'players'

    player_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False)
    name = db.Column(db.String, nullable=False)
    character_name = db.Column(db.String, nullable=False)
    race = db.Column(db.String)
    class_ = db.Column(db.String)
    level = db.Column(db.Integer, default=1)
    stats = db.Column(db.Text)
    inventory = db.Column(db.Text)
    character_sheet = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    campaign = db.relationship('Campaign', backref='players')


class Session(db.Model):
    __tablename__ = 'sessions'

    session_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False)
    state_snapshot = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    campaign = db.relationship('Campaign', backref='sessions')
    log_entries = db.relationship('SessionLogEntry', backref='session', cascade='all, delete-orphan')
    dm_turns = db.relationship('DmTurn', backref='session', cascade='all, delete-orphan')
    turn_events = db.relationship('TurnEvent', backref='session', cascade='all, delete-orphan')


class Npc(db.Model):
    __tablename__ = 'npcs'

    npc_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    world_id = db.Column(db.Integer, db.ForeignKey('worlds.world_id'), nullable=False)
    name = db.Column(db.String, nullable=False)
    role = db.Column(db.String)
    backstory = db.Column(db.Text)

    world = db.relationship('World', backref='npcs')


class PlayerAction(db.Model):
    __tablename__ = 'player_actions'

    action_id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=False)
    action_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=utc_now)

    player = db.relationship('Player', backref='actions')
    session = db.relationship('Session', backref='player_actions')


class StoryEvent(db.Model):
    __tablename__ = 'story_events'

    event_id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'))
    description = db.Column(db.Text)
    importance = db.Column(db.Integer)
    resolved = db.Column(db.Boolean, default=False)


class SessionLogEntry(db.Model):
    __tablename__ = 'session_log_entries'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    entry_type = db.Column(db.String, nullable=False)
    metadata_json = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=utc_now)


class CampaignSegment(db.Model):
    """Represents a discrete story segment or milestone within a campaign."""

    __tablename__ = 'campaign_segments'

    segment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.Text, nullable=True)
    trigger_condition = db.Column(db.Text, nullable=True)
    tags = db.Column(db.Text, nullable=True)
    is_triggered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    campaign = db.relationship('Campaign', backref='segments')


class DmTurn(db.Model):
    __tablename__ = 'dm_turns'

    turn_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=False, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=True, index=True)

    player_input = db.Column(db.Text, nullable=False)
    dm_output = db.Column(db.Text)

    requires_roll = db.Column(db.Boolean, default=False)
    rule_type = db.Column(db.String)
    confidence = db.Column(db.Float)
    roll_value = db.Column(db.Integer)
    outcome_status = db.Column(db.String, default='resolved')
    rules_hint = db.Column(db.Text)
    context_version = db.Column(db.String, default='v2')

    status = db.Column(db.String, default='pending')
    latency_ms = db.Column(db.Integer)
    llm_provider = db.Column(db.String)
    llm_model = db.Column(db.String)
    metadata_json = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utc_now)
    completed_at = db.Column(db.DateTime)

    campaign = db.relationship('Campaign', backref='dm_turns')
    player = db.relationship('Player', backref='dm_turns')


class TurnEvent(db.Model):
    __tablename__ = 'turn_events'

    event_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=False, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False, index=True)
    turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.player_id'), nullable=True, index=True)
    event_type = db.Column(db.String, nullable=False, index=True)
    payload_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, index=True)

    campaign = db.relationship('Campaign', backref='turn_events')
    turn = db.relationship('DmTurn', backref='turn_events')
    player = db.relationship('Player', backref='turn_events')


class DmCoherenceFeedback(db.Model):
    __tablename__ = 'dm_coherence_feedback'

    feedback_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=False, index=True)
    turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    coherence_score = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    session = db.relationship('Session', backref='coherence_feedback')
    turn = db.relationship('DmTurn', backref='coherence_feedback')


class StoryEntity(db.Model):
    __tablename__ = 'story_entities'

    entity_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=True, index=True)

    entity_type = db.Column(db.String, nullable=False, index=True)
    name = db.Column(db.String, nullable=False)
    canonical_name = db.Column(db.String)
    summary = db.Column(db.Text)
    status = db.Column(db.String, default='active')
    aliases_json = db.Column(db.Text)
    metadata_json = db.Column(db.Text)

    first_seen_turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    last_seen_turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    campaign = db.relationship('Campaign', backref='story_entities')
    session = db.relationship('Session', backref='story_entities')
    first_seen_turn = db.relationship('DmTurn', foreign_keys=[first_seen_turn_id], backref='first_seen_entities')
    last_seen_turn = db.relationship('DmTurn', foreign_keys=[last_seen_turn_id], backref='last_seen_entities')


class StoryFact(db.Model):
    __tablename__ = 'story_facts'

    fact_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False, index=True)
    subject_entity_id = db.Column(db.Integer, db.ForeignKey('story_entities.entity_id'), nullable=True, index=True)
    predicate = db.Column(db.String, nullable=False, index=True)
    object_entity_id = db.Column(db.Integer, db.ForeignKey('story_entities.entity_id'), nullable=True, index=True)
    value_text = db.Column(db.Text)
    value_json = db.Column(db.Text)
    fact_status = db.Column(db.String, default='accepted')
    confidence = db.Column(db.Float)
    source_turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    supersedes_fact_id = db.Column(db.Integer, db.ForeignKey('story_facts.fact_id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    campaign = db.relationship('Campaign', backref='story_facts')
    subject_entity = db.relationship('StoryEntity', foreign_keys=[subject_entity_id], backref='outbound_facts')
    object_entity = db.relationship('StoryEntity', foreign_keys=[object_entity_id], backref='inbound_facts')
    source_turn = db.relationship('DmTurn', foreign_keys=[source_turn_id], backref='story_facts')
    supersedes_fact = db.relationship('StoryFact', remote_side=[fact_id], backref='superseded_by')


class StoryThread(db.Model):
    __tablename__ = 'story_threads'

    thread_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False, index=True)
    title = db.Column(db.String, nullable=False)
    summary = db.Column(db.Text)
    status = db.Column(db.String, default='open', index=True)
    priority = db.Column(db.Integer, default=1)
    origin_turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    last_touched_turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    resolved_turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=True, index=True)
    source = db.Column(db.String, default='emergent')
    metadata_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    campaign = db.relationship('Campaign', backref='story_threads')
    origin_turn = db.relationship('DmTurn', foreign_keys=[origin_turn_id], backref='origin_story_threads')
    last_touched_turn = db.relationship('DmTurn', foreign_keys=[last_touched_turn_id], backref='touched_story_threads')
    resolved_turn = db.relationship('DmTurn', foreign_keys=[resolved_turn_id], backref='resolved_story_threads')


class TurnCanonUpdate(db.Model):
    __tablename__ = 'turn_canon_updates'

    update_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    turn_id = db.Column(db.Integer, db.ForeignKey('dm_turns.turn_id'), nullable=False, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.campaign_id'), nullable=False, index=True)
    raw_patch_json = db.Column(db.Text)
    applied_patch_json = db.Column(db.Text)
    status = db.Column(db.String, default='pending', index=True)
    extractor_model = db.Column(db.String)
    error_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)

    turn = db.relationship('DmTurn', backref='canon_updates')
    campaign = db.relationship('Campaign', backref='canon_updates')


class SessionState(db.Model):
    __tablename__ = 'session_states'

    state_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.session_id'), nullable=False, unique=True, index=True)

    rolling_summary = db.Column(db.Text)
    current_location = db.Column(db.Text)
    current_quest = db.Column(db.Text)
    active_segments = db.Column(db.Text)
    memory_snippets = db.Column(db.Text)

    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


def safe_json_loads(raw_value, default):
    if raw_value is None:
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return default


def safe_json_dumps(value, default):
    payload = value if value is not None else default
    return json.dumps(payload)


def get_full_session_log(session_id: int) -> str:
    entries = (
        SessionLogEntry.query.filter_by(session_id=session_id)
        .order_by(SessionLogEntry.timestamp.asc(), SessionLogEntry.id.asc())
        .all()
    )
    return "\n".join(entry.message for entry in entries)


def get_or_create_session_state(session_id: int, campaign: Campaign | None = None) -> SessionState:
    session_state = SessionState.query.filter_by(session_id=session_id).first()
    if session_state:
        return session_state

    session_state = SessionState(
        session_id=session_id,
        current_location=(campaign.location if campaign else None),
        current_quest=(campaign.current_quest if campaign else None),
        rolling_summary='',
        active_segments=safe_json_dumps([], []),
        memory_snippets=safe_json_dumps([], []),
    )
    db.session.add(session_state)
    return session_state
