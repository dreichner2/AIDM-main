from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import World
from aidm_server.validation import missing_fields, parse_json_body


logger = logging.getLogger(__name__)
worlds_bp = Blueprint('worlds', __name__)


def _world_payload(world: World) -> dict:
    return {
        'world_id': world.world_id,
        'name': world.name,
        'description': world.description,
        'created_at': world.created_at.isoformat() if world.created_at else None,
    }


@worlds_bp.route('', methods=['POST'])
def create_world():
    payload = parse_json_body(request)
    required = missing_fields(payload, ['name'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    try:
        new_world = World(
            name=payload['name'],
            description=payload.get('description', ''),
        )
        db.session.add(new_world)
        db.session.commit()
        return jsonify({'world_id': new_world.world_id}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to create world: %s', str(exc))
        return error_response('world_create_failed', 'Failed to create world.', 400)


@worlds_bp.route('', methods=['GET'])
def list_worlds():
    worlds = World.query.order_by(World.created_at.desc(), World.world_id.desc()).all()
    return jsonify([_world_payload(world) for world in worlds])


@worlds_bp.route('/<int:world_id>', methods=['GET'])
def get_world(world_id):
    world = db.session.get(World, world_id)
    if not world:
        return error_response('world_not_found', 'World not found.', 404)

    return jsonify(_world_payload(world))
