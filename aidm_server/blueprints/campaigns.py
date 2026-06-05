from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import (
    Campaign,
    CampaignSegment,
    DmTurn,
    Map,
    Player,
    Session,
    SessionLogEntry,
    SessionState,
    StoryEntity,
    StoryFact,
    StoryThread,
    TurnCanonUpdate,
    World,
    safe_json_loads,
)
from aidm_server.validation import coerce_int, missing_fields, parse_json_body


logger = logging.getLogger(__name__)
campaigns_bp = Blueprint('campaigns', __name__)
CAMPAIGN_TITLE_MAX_LENGTH = 120
CAMPAIGN_TEXT_MAX_LENGTH = 2000


def _isoformat(value):
    return value.isoformat() if value else None


def _optional_text(value, *, max_length: int, field: str, default: str | None = ''):
    if value is None:
        return default, None
    text = str(value).strip()
    if len(text) > max_length:
        return None, f'{field} must be {max_length} characters or fewer.'
    return text, None


def _required_text(value, *, max_length: int, field: str):
    text, error = _optional_text(value, max_length=max_length, field=field, default='')
    if error:
        return None, error
    if not text:
        return None, f'{field} is required.'
    return text, None


def _latest_isoformat(*values):
    iso_values = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            iso_values.append(value)
        else:
            iso_values.append(value.isoformat())
    return max(iso_values) if iso_values else None


def _campaign_session_summary(campaign: Campaign) -> dict:
    session_count = db.session.query(func.count(Session.session_id)).filter_by(campaign_id=campaign.campaign_id).scalar() or 0
    latest_session = (
        Session.query.filter_by(campaign_id=campaign.campaign_id)
        .order_by(Session.created_at.desc(), Session.session_id.desc())
        .first()
    )
    latest_log_at = (
        db.session.query(func.max(SessionLogEntry.timestamp))
        .join(Session, Session.session_id == SessionLogEntry.session_id)
        .filter(Session.campaign_id == campaign.campaign_id)
        .scalar()
    )
    latest_state_at = (
        db.session.query(func.max(SessionState.updated_at))
        .join(Session, Session.session_id == SessionState.session_id)
        .filter(Session.campaign_id == campaign.campaign_id)
        .scalar()
    )
    latest_turn_created_at = db.session.query(func.max(DmTurn.created_at)).filter_by(campaign_id=campaign.campaign_id).scalar()
    latest_turn_completed_at = db.session.query(func.max(DmTurn.completed_at)).filter_by(campaign_id=campaign.campaign_id).scalar()

    return {
        'session_count': int(session_count),
        'latest_session_id': latest_session.session_id if latest_session else None,
        'latest_activity_at': _latest_isoformat(
            campaign.created_at,
            latest_session.created_at if latest_session else None,
            latest_log_at,
            latest_state_at,
            latest_turn_created_at,
            latest_turn_completed_at,
        ),
    }


def _campaign_payload(campaign: Campaign) -> dict:
    return {
        'campaign_id': campaign.campaign_id,
        'title': campaign.title,
        'description': campaign.description,
        'world_id': campaign.world_id,
        'created_at': _isoformat(campaign.created_at),
        'current_quest': campaign.current_quest,
        'location': campaign.location,
        **_campaign_session_summary(campaign),
    }


def _player_payload(player: Player) -> dict:
    return {
        'player_id': player.player_id,
        'campaign_id': player.campaign_id,
        'name': player.name,
        'character_name': player.character_name,
        'race': player.race,
        'class_': player.class_,
        'char_class': player.class_,
        'level': player.level,
    }


def _map_payload(map_obj: Map) -> dict:
    return {
        'map_id': map_obj.map_id,
        'world_id': map_obj.world_id,
        'campaign_id': map_obj.campaign_id,
        'title': map_obj.title,
        'description': map_obj.description,
        'map_data': safe_json_loads(map_obj.map_data, {}),
        'created_at': _isoformat(map_obj.created_at),
    }


def _segment_payload(segment: CampaignSegment) -> dict:
    return {
        'segment_id': segment.segment_id,
        'campaign_id': segment.campaign_id,
        'title': segment.title,
        'description': segment.description,
        'trigger_condition': segment.trigger_condition,
        'tags': segment.tags,
        'is_triggered': segment.is_triggered,
        'created_at': _isoformat(segment.created_at),
    }


def _session_snapshot(session_obj: Session) -> dict:
    snapshot = safe_json_loads(session_obj.state_snapshot, {})
    return snapshot if isinstance(snapshot, dict) else {}


def _session_display_name(session_obj: Session, snapshot: dict) -> str:
    raw_name = snapshot.get('name') or snapshot.get('title')
    name = str(raw_name or '').strip()
    return name or f"Session {session_obj.session_id}"


def _session_payload(session_obj: Session) -> dict:
    snapshot = _session_snapshot(session_obj)
    session_state = SessionState.query.filter_by(session_id=session_obj.session_id).first()
    latest_log_at = db.session.query(func.max(SessionLogEntry.timestamp)).filter_by(session_id=session_obj.session_id).scalar()
    latest_turn_created_at = db.session.query(func.max(DmTurn.created_at)).filter_by(session_id=session_obj.session_id).scalar()
    latest_turn_completed_at = db.session.query(func.max(DmTurn.completed_at)).filter_by(session_id=session_obj.session_id).scalar()
    turn_count = db.session.query(func.count(DmTurn.turn_id)).filter_by(session_id=session_obj.session_id).scalar() or 0
    snapshot_updated_at = snapshot.get('updated_at')
    latest_activity = _latest_isoformat(
        session_obj.created_at,
        snapshot_updated_at if isinstance(snapshot_updated_at, str) else None,
        session_state.updated_at if session_state else None,
        latest_log_at,
        latest_turn_created_at,
        latest_turn_completed_at,
    )
    latest_summary = ''
    if session_state and session_state.rolling_summary:
        latest_summary = session_state.rolling_summary
    elif isinstance(snapshot.get('recap'), str):
        latest_summary = snapshot['recap']
    elif isinstance(snapshot.get('summary'), str):
        latest_summary = snapshot['summary']

    return {
        'session_id': session_obj.session_id,
        'campaign_id': session_obj.campaign_id,
        'created_at': _isoformat(session_obj.created_at),
        'updated_at': latest_activity,
        'latest_activity_at': latest_activity,
        'display_name': _session_display_name(session_obj, snapshot),
        'turn_count': int(turn_count),
        'latest_summary': latest_summary,
        'is_archived': bool(snapshot.get('is_archived') or snapshot.get('archived')),
        'state_snapshot': safe_json_loads(session_obj.state_snapshot, None),
    }


def _entity_payload(entity: StoryEntity) -> dict:
    return {
        'entity_id': entity.entity_id,
        'campaign_id': entity.campaign_id,
        'session_id': entity.session_id,
        'entity_type': entity.entity_type,
        'name': entity.name,
        'canonical_name': entity.canonical_name,
        'summary': entity.summary,
        'status': entity.status,
        'aliases': safe_json_loads(entity.aliases_json, []),
        'metadata': safe_json_loads(entity.metadata_json, {}),
        'first_seen_turn_id': entity.first_seen_turn_id,
        'last_seen_turn_id': entity.last_seen_turn_id,
        'created_at': _isoformat(entity.created_at),
        'updated_at': _isoformat(entity.updated_at),
    }


def _fact_payload(fact: StoryFact) -> dict:
    return {
        'fact_id': fact.fact_id,
        'campaign_id': fact.campaign_id,
        'subject_entity_id': fact.subject_entity_id,
        'subject_name': fact.subject_entity.name if fact.subject_entity else None,
        'predicate': fact.predicate,
        'object_entity_id': fact.object_entity_id,
        'object_name': fact.object_entity.name if fact.object_entity else None,
        'value_text': fact.value_text,
        'value_json': safe_json_loads(fact.value_json, None),
        'fact_status': fact.fact_status,
        'confidence': fact.confidence,
        'source_turn_id': fact.source_turn_id,
        'supersedes_fact_id': fact.supersedes_fact_id,
        'created_at': _isoformat(fact.created_at),
    }


def _thread_payload(thread: StoryThread) -> dict:
    return {
        'thread_id': thread.thread_id,
        'campaign_id': thread.campaign_id,
        'title': thread.title,
        'summary': thread.summary,
        'status': thread.status,
        'priority': thread.priority,
        'origin_turn_id': thread.origin_turn_id,
        'last_touched_turn_id': thread.last_touched_turn_id,
        'resolved_turn_id': thread.resolved_turn_id,
        'source': thread.source,
        'metadata': safe_json_loads(thread.metadata_json, {}),
        'created_at': _isoformat(thread.created_at),
        'updated_at': _isoformat(thread.updated_at),
    }


def _canon_update_payload(update: TurnCanonUpdate) -> dict:
    return {
        'update_id': update.update_id,
        'turn_id': update.turn_id,
        'campaign_id': update.campaign_id,
        'raw_patch': safe_json_loads(update.raw_patch_json, None),
        'applied_patch': safe_json_loads(update.applied_patch_json, None),
        'status': update.status,
        'extractor_model': update.extractor_model,
        'error_text': update.error_text,
        'created_at': _isoformat(update.created_at),
    }


@campaigns_bp.route('', methods=['POST'])
def create_campaign():
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    required = missing_fields(payload, ['title', 'world_id'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    title, title_error = _required_text(
        payload.get('title'),
        max_length=CAMPAIGN_TITLE_MAX_LENGTH,
        field='title',
    )
    if title_error:
        return error_response('validation_error', title_error, 400)

    world_id = coerce_int(payload.get('world_id'))
    if world_id is None or world_id < 1:
        return error_response('validation_error', 'Campaign title and a valid world ID are required.', 400)
    description, description_error = _optional_text(
        payload.get('description', ''),
        max_length=CAMPAIGN_TEXT_MAX_LENGTH,
        field='description',
    )
    if description_error:
        return error_response('validation_error', description_error, 400)
    current_quest, current_quest_error = _optional_text(
        payload.get('current_quest'),
        max_length=CAMPAIGN_TEXT_MAX_LENGTH,
        field='current_quest',
        default=None,
    )
    if current_quest_error:
        return error_response('validation_error', current_quest_error, 400)
    location, location_error = _optional_text(
        payload.get('location'),
        max_length=CAMPAIGN_TEXT_MAX_LENGTH,
        field='location',
        default=None,
    )
    if location_error:
        return error_response('validation_error', location_error, 400)

    world = db.session.get(World, world_id)
    if not world:
        return error_response('world_not_found', 'World not found.', 404)

    try:
        new_campaign = Campaign(
            title=title,
            description=description,
            world_id=world_id,
            current_quest=current_quest,
            location=location,
        )
        db.session.add(new_campaign)
        db.session.commit()
        return jsonify({'campaign_id': new_campaign.campaign_id}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to create campaign: %s', str(exc))
        return error_response('campaign_create_failed', 'Failed to create campaign.', 400)


@campaigns_bp.route('', methods=['GET'])
def list_campaigns():
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).all()
    return jsonify(
        [_campaign_payload(campaign) for campaign in campaigns]
    )


@campaigns_bp.route('/<int:campaign_id>', methods=['GET'])
def get_campaign(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    return jsonify(_campaign_payload(campaign))


@campaigns_bp.route('/<int:campaign_id>/workspace', methods=['GET'])
def get_campaign_workspace(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    sessions = Session.query.filter_by(campaign_id=campaign_id).order_by(Session.created_at.desc()).all()
    session_payloads = [_session_payload(session_obj) for session_obj in sessions]
    session_payloads.sort(key=lambda item: item.get('latest_activity_at') or '', reverse=True)
    players = Player.query.filter_by(campaign_id=campaign_id).order_by(Player.created_at.asc(), Player.player_id.asc()).all()
    maps = Map.query.filter_by(campaign_id=campaign_id).order_by(Map.created_at.desc()).all()
    segments = CampaignSegment.query.filter_by(campaign_id=campaign_id).order_by(CampaignSegment.created_at.desc()).all()
    latest_session = session_payloads[0] if session_payloads else None

    return jsonify(
        {
            'campaign': _campaign_payload(campaign),
            'sessions': session_payloads,
            'players': [_player_payload(player) for player in players],
            'maps': [_map_payload(map_obj) for map_obj in maps],
            'segments': [_segment_payload(segment) for segment in segments],
            'summary': {
                'session_count': len(session_payloads),
                'player_count': len(players),
                'map_count': len(maps),
                'segment_count': len(segments),
                'latest_session_id': latest_session['session_id'] if latest_session else None,
                'latest_activity_at': latest_session['latest_activity_at'] if latest_session else _isoformat(campaign.created_at),
            },
        }
    )


@campaigns_bp.route('/<int:campaign_id>/canon', methods=['GET'])
def get_campaign_canon(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    entities = StoryEntity.query.filter_by(campaign_id=campaign_id).order_by(StoryEntity.updated_at.desc()).all()
    facts = StoryFact.query.filter_by(campaign_id=campaign_id).order_by(StoryFact.created_at.desc()).all()
    threads = StoryThread.query.filter_by(campaign_id=campaign_id).order_by(StoryThread.updated_at.desc()).all()
    updates = TurnCanonUpdate.query.filter_by(campaign_id=campaign_id).order_by(TurnCanonUpdate.created_at.desc()).all()

    return jsonify(
        {
            'campaign_id': campaign_id,
            'entities': [_entity_payload(entity) for entity in entities],
            'facts': [_fact_payload(fact) for fact in facts],
            'threads': [_thread_payload(thread) for thread in threads],
            'updates': [_canon_update_payload(update) for update in updates],
            'summary': {
                'entity_count': len(entities),
                'fact_count': len(facts),
                'thread_count': len(threads),
                'update_count': len(updates),
            },
        }
    )
