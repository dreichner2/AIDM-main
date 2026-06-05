from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import Campaign, CampaignSegment
from aidm_server.validation import coerce_bool, missing_fields, parse_json_body


logger = logging.getLogger(__name__)
segments_bp = Blueprint('segments', __name__)


@segments_bp.route('', methods=['POST'])
def create_segment():
    payload = parse_json_body(request)
    required = missing_fields(payload, ['campaign_id', 'title'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    campaign = db.session.get(Campaign, payload['campaign_id'])
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    try:
        is_triggered = coerce_bool(payload.get('is_triggered'), False)
        if is_triggered is None:
            return error_response('validation_error', 'is_triggered must be a boolean value.', 400)

        segment = CampaignSegment(
            campaign_id=payload['campaign_id'],
            title=payload['title'],
            description=payload.get('description', ''),
            trigger_condition=payload.get('trigger_condition', ''),
            tags=payload.get('tags', ''),
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

    query = CampaignSegment.query
    if campaign_id is not None:
        campaign = db.session.get(Campaign, campaign_id)
        if not campaign:
            return error_response('campaign_not_found', 'Campaign not found.', 404)
        query = query.filter_by(campaign_id=campaign_id)

    segments = query.order_by(CampaignSegment.created_at.desc()).all()
    return jsonify(
        [
            {
                'segment_id': seg.segment_id,
                'campaign_id': seg.campaign_id,
                'title': seg.title,
                'description': seg.description,
                'trigger_condition': seg.trigger_condition,
                'tags': seg.tags,
                'is_triggered': seg.is_triggered,
                'created_at': seg.created_at.isoformat() if seg.created_at else None,
            }
            for seg in segments
        ]
    ), 200


@segments_bp.route('/<int:segment_id>', methods=['GET'])
def get_segment(segment_id):
    seg = db.session.get(CampaignSegment, segment_id)
    if not seg:
        return error_response('segment_not_found', 'Segment not found.', 404)

    return jsonify(
        {
            'segment_id': seg.segment_id,
            'campaign_id': seg.campaign_id,
            'title': seg.title,
            'description': seg.description,
            'trigger_condition': seg.trigger_condition,
            'tags': seg.tags,
            'is_triggered': seg.is_triggered,
            'created_at': seg.created_at.isoformat() if seg.created_at else None,
        }
    ), 200


@segments_bp.route('/<int:segment_id>', methods=['PUT', 'PATCH'])
def update_segment(segment_id):
    seg = db.session.get(CampaignSegment, segment_id)
    if not seg:
        return error_response('segment_not_found', 'Segment not found.', 404)

    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    try:
        seg.title = payload.get('title', seg.title)
        seg.description = payload.get('description', seg.description)
        seg.trigger_condition = payload.get('trigger_condition', seg.trigger_condition)
        seg.tags = payload.get('tags', seg.tags)
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
    seg = db.session.get(CampaignSegment, segment_id)
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
