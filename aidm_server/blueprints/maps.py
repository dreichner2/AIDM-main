from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import Campaign, Map, World, safe_json_loads
from aidm_server.validation import missing_fields, parse_json_body


logger = logging.getLogger(__name__)
maps_bp = Blueprint('maps', __name__)


@maps_bp.route('', methods=['POST'])
def create_map():
    payload = parse_json_body(request)
    required = missing_fields(payload, ['title'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    world_id = payload.get('world_id')
    campaign_id = payload.get('campaign_id')

    world = db.session.get(World, world_id) if world_id is not None else None
    campaign = db.session.get(Campaign, campaign_id) if campaign_id is not None else None

    if world_id is not None and not world:
        return error_response('world_not_found', 'World not found.', 404)
    if campaign_id is not None and not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)
    if world and campaign and campaign.world_id != world.world_id:
        return error_response(
            'campaign_world_mismatch',
            'Campaign does not belong to the provided world.',
            400,
        )

    try:
        new_map = Map(
            world_id=world_id,
            campaign_id=campaign_id,
            title=payload['title'],
            description=payload.get('description', ''),
            map_data=json.dumps(payload.get('map_data', {})),
        )
        db.session.add(new_map)
        db.session.commit()
        return jsonify({'map_id': new_map.map_id}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to create map: %s', str(exc))
        return error_response('map_create_failed', 'Failed to create map.', 400)


@maps_bp.route('', methods=['GET'])
def list_maps():
    world_id = request.args.get('world_id', type=int)
    campaign_id = request.args.get('campaign_id', type=int)

    query = Map.query
    if world_id is not None:
        world = db.session.get(World, world_id)
        if not world:
            return error_response('world_not_found', 'World not found.', 404)
        query = query.filter_by(world_id=world_id)
    if campaign_id is not None:
        campaign = db.session.get(Campaign, campaign_id)
        if not campaign:
            return error_response('campaign_not_found', 'Campaign not found.', 404)
        query = query.filter_by(campaign_id=campaign_id)

    maps = query.order_by(Map.created_at.desc()).all()
    return jsonify(
        [
            {
                'map_id': m.map_id,
                'world_id': m.world_id,
                'campaign_id': m.campaign_id,
                'title': m.title,
                'description': m.description,
                'map_data': safe_json_loads(m.map_data, {}),
                'created_at': m.created_at.isoformat() if m.created_at else None,
            }
            for m in maps
        ]
    )


@maps_bp.route('/<int:map_id>', methods=['GET'])
def get_map(map_id):
    map_obj = db.session.get(Map, map_id)
    if not map_obj:
        return error_response('map_not_found', 'Map not found.', 404)

    return jsonify(
        {
            'map_id': map_obj.map_id,
            'world_id': map_obj.world_id,
            'campaign_id': map_obj.campaign_id,
            'title': map_obj.title,
            'description': map_obj.description,
            'map_data': safe_json_loads(map_obj.map_data, {}),
            'created_at': map_obj.created_at.isoformat() if map_obj.created_at else None,
        }
    )


@maps_bp.route('/<int:map_id>', methods=['PUT', 'PATCH'])
def update_map(map_id):
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    map_obj = db.session.get(Map, map_id)
    if not map_obj:
        return error_response('map_not_found', 'Map not found.', 404)

    try:
        map_obj.title = payload.get('title', map_obj.title)
        map_obj.description = payload.get('description', map_obj.description)
        if 'map_data' in payload:
            map_obj.map_data = json.dumps(payload['map_data'])
        db.session.commit()
        return jsonify({'message': 'Map updated successfully'}), 200
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to update map: %s', str(exc))
        return error_response('map_update_failed', 'Failed to update map.', 400)
