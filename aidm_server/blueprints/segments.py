from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import Campaign, CampaignSegment
from aidm_server.pagination import jsonify_page, limited_page
from aidm_server.response_dtos import segment_payload
from aidm_server.validation import (
    coerce_bool,
    coerce_int,
    optional_text,
    parse_json_body,
    positive_int,
    required_text,
)
from aidm_server.workspace_access import current_workspace_id, get_campaign as workspace_campaign, get_segment as workspace_segment


logger = logging.getLogger(__name__)
segments_bp = Blueprint('segments', __name__)
SEGMENT_TITLE_MAX_LENGTH = 120
SEGMENT_TEXT_MAX_LENGTH = 2000
SEGMENT_TAGS_MAX_LENGTH = 500


@segments_bp.route('', methods=['POST'])
def create_segment():
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    campaign_id, campaign_id_error = positive_int(payload.get('campaign_id'), field='campaign_id', required=True)
    if campaign_id_error:
        return error_response('validation_error', campaign_id_error, 400)
    title, title_error = required_text(payload.get('title'), max_length=SEGMENT_TITLE_MAX_LENGTH, field='title')
    if title_error:
        return error_response('validation_error', title_error, 400)
    description, description_error = optional_text(
        payload.get('description', ''),
        max_length=SEGMENT_TEXT_MAX_LENGTH,
        field='description',
    )
    if description_error:
        return error_response('validation_error', description_error, 400)
    trigger_condition, trigger_condition_error = optional_text(
        payload.get('trigger_condition', ''),
        max_length=SEGMENT_TEXT_MAX_LENGTH,
        field='trigger_condition',
    )
    if trigger_condition_error:
        return error_response('validation_error', trigger_condition_error, 400)
    tags, tags_error = optional_text(payload.get('tags', ''), max_length=SEGMENT_TAGS_MAX_LENGTH, field='tags')
    if tags_error:
        return error_response('validation_error', tags_error, 400)

    campaign = workspace_campaign(campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    try:
        is_triggered = coerce_bool(payload.get('is_triggered'), False)
        if is_triggered is None:
            return error_response('validation_error', 'is_triggered must be a boolean value.', 400)

        segment = CampaignSegment(
            campaign_id=campaign_id,
            title=title,
            description=description,
            trigger_condition=trigger_condition,
            tags=tags,
            is_triggered=is_triggered,
        )
        db.session.add(segment)
        db.session.commit()
        return jsonify({'segment_id': segment.segment_id}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to create segment: %s', str(exc))
        return error_response('segment_create_failed', 'Failed to create segment.', 400)


@segments_bp.route('', methods=['GET'])
def list_segments():
    campaign_id = request.args.get('campaign_id', type=int)
    before_id = coerce_int(request.args.get('before_id'))
    limit = coerce_int(request.args.get('limit'))

    query = CampaignSegment.query.join(Campaign)
    query = query.filter(Campaign.workspace_id == current_workspace_id())
    if campaign_id is not None:
        campaign = workspace_campaign(campaign_id)
        if not campaign:
            return error_response('campaign_not_found', 'Campaign not found.', 404)
        query = query.filter(CampaignSegment.campaign_id == campaign_id)
    if before_id is not None:
        query = query.filter(CampaignSegment.segment_id < before_id)
    query = query.order_by(CampaignSegment.created_at.desc(), CampaignSegment.segment_id.desc())
    segments = limited_page(query, limit=limit)
    return jsonify_page(segments, payload_for=segment_payload, cursor_for=lambda segment: segment.segment_id), 200


@segments_bp.route('/activate', methods=['POST'])
def activate_segment():
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    campaign_id, campaign_id_error = positive_int(payload.get('campaign_id'), field='campaign_id', required=True)
    if campaign_id_error:
        return error_response('validation_error', campaign_id_error, 400)
    segment_id, segment_id_error = positive_int(payload.get('segment_id'), field='segment_id', required=True)
    if segment_id_error:
        return error_response('validation_error', segment_id_error, 400)
    exclusive = coerce_bool(payload.get('exclusive'), True)
    if exclusive is None:
        return error_response('validation_error', 'exclusive must be a boolean value.', 400)

    campaign = workspace_campaign(campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)
    segment = workspace_segment(segment_id)
    if not segment or segment.campaign_id != campaign_id:
        return error_response('segment_not_found', 'Segment not found.', 404)

    try:
        if exclusive:
            CampaignSegment.query.filter_by(campaign_id=campaign_id).update(
                {CampaignSegment.is_triggered: False},
                synchronize_session=False,
            )
            db.session.flush()
            segment = db.session.get(CampaignSegment, segment_id)
        segment.is_triggered = True
        db.session.commit()
        segments = (
            CampaignSegment.query.filter_by(campaign_id=campaign_id)
            .order_by(CampaignSegment.created_at.desc(), CampaignSegment.segment_id.desc())
            .all()
        )
        return jsonify({'segments': [segment_payload(seg) for seg in segments]}), 200
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to activate segment: %s', str(exc))
        return error_response('segment_activate_failed', 'Failed to activate segment.', 400)


@segments_bp.route('/<int:segment_id>', methods=['GET'])
def get_segment(segment_id):
    seg = workspace_segment(segment_id)
    if not seg:
        return error_response('segment_not_found', 'Segment not found.', 404)

    return jsonify(segment_payload(seg)), 200


@segments_bp.route('/<int:segment_id>', methods=['PUT', 'PATCH'])
def update_segment(segment_id):
    seg = workspace_segment(segment_id)
    if not seg:
        return error_response('segment_not_found', 'Segment not found.', 404)

    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    try:
        if 'title' in payload:
            title, title_error = required_text(payload.get('title'), max_length=SEGMENT_TITLE_MAX_LENGTH, field='title')
            if title_error:
                return error_response('validation_error', title_error, 400)
            seg.title = title
        if 'description' in payload:
            description, description_error = optional_text(
                payload.get('description'),
                max_length=SEGMENT_TEXT_MAX_LENGTH,
                field='description',
            )
            if description_error:
                return error_response('validation_error', description_error, 400)
            seg.description = description
        if 'trigger_condition' in payload:
            trigger_condition, trigger_condition_error = optional_text(
                payload.get('trigger_condition'),
                max_length=SEGMENT_TEXT_MAX_LENGTH,
                field='trigger_condition',
            )
            if trigger_condition_error:
                return error_response('validation_error', trigger_condition_error, 400)
            seg.trigger_condition = trigger_condition
        if 'tags' in payload:
            tags, tags_error = optional_text(payload.get('tags'), max_length=SEGMENT_TAGS_MAX_LENGTH, field='tags')
            if tags_error:
                return error_response('validation_error', tags_error, 400)
            seg.tags = tags
        if 'is_triggered' in payload:
            is_triggered = coerce_bool(payload['is_triggered'])
            if is_triggered is None:
                return error_response('validation_error', 'is_triggered must be a boolean value.', 400)
            seg.is_triggered = is_triggered

        db.session.commit()
        return jsonify({'message': 'Segment updated successfully'}), 200
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to update segment: %s', str(exc))
        return error_response('segment_update_failed', 'Failed to update segment.', 400)


@segments_bp.route('/<int:segment_id>', methods=['DELETE'])
def delete_segment(segment_id):
    seg = workspace_segment(segment_id)
    if not seg:
        return error_response('segment_not_found', 'Segment not found.', 404)

    try:
        db.session.delete(seg)
        db.session.commit()
        return jsonify({'message': 'Segment deleted'}), 200
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to delete segment: %s', str(exc))
        return error_response('segment_delete_failed', 'Failed to delete segment.', 400)
