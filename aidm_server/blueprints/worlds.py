from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from aidm_server.database import db
from aidm_server.errors import error_response
from aidm_server.models import Campaign, Map, Npc, World
from aidm_server.pagination import jsonify_page, limited_page
from aidm_server.response_dtos import world_payload
from aidm_server.validation import coerce_int, optional_text, parse_json_body, required_text
from aidm_server.workspace_access import current_workspace_id, get_world as workspace_world, world_query


logger = logging.getLogger(__name__)
worlds_bp = Blueprint('worlds', __name__)
WORLD_NAME_MAX_LENGTH = 120
WORLD_DESCRIPTION_MAX_LENGTH = 2000


@worlds_bp.route('', methods=['POST'])
def create_world():
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    name, name_error = required_text(payload.get('name'), max_length=WORLD_NAME_MAX_LENGTH, field='name')
    if name_error:
        return error_response('validation_error', name_error, 400)
    description, description_error = optional_text(
        payload.get('description', ''),
        max_length=WORLD_DESCRIPTION_MAX_LENGTH,
        field='description',
    )
    if description_error:
        return error_response('validation_error', description_error, 400)

    try:
        new_world = World(
            workspace_id=current_workspace_id(),
            name=name,
            description=description,
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
    before_id = coerce_int(request.args.get('before_id'))
    limit = coerce_int(request.args.get('limit'))
    query = world_query()
    if before_id is not None:
        query = query.filter(World.world_id < before_id)
    query = query.order_by(World.created_at.desc(), World.world_id.desc())
    worlds = limited_page(query, limit=limit)
    return jsonify_page(worlds, payload_for=world_payload, cursor_for=lambda world: world.world_id)


@worlds_bp.route('/<int:world_id>', methods=['GET'])
def get_world(world_id):
    world = workspace_world(world_id)
    if not world:
        return error_response('world_not_found', 'World not found.', 404)

    return jsonify(world_payload(world))


@worlds_bp.route('/<int:world_id>', methods=['PATCH'])
def update_world(world_id):
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    world = workspace_world(world_id)
    if not world:
        return error_response('world_not_found', 'World not found.', 404)

    if 'name' not in payload and 'description' not in payload:
        return error_response('validation_error', 'No supported world fields were provided.', 400)

    try:
        if 'name' in payload:
            name, name_error = required_text(payload.get('name'), max_length=WORLD_NAME_MAX_LENGTH, field='name')
            if name_error:
                return error_response('validation_error', name_error, 400)
            world.name = name
        if 'description' in payload:
            description, description_error = optional_text(
                payload.get('description', ''),
                max_length=WORLD_DESCRIPTION_MAX_LENGTH,
                field='description',
            )
            if description_error:
                return error_response('validation_error', description_error, 400)
            world.description = description
        db.session.commit()
        return jsonify(world_payload(world))
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to update world: %s', str(exc))
        return error_response('world_update_failed', 'Failed to update world.', 400)


@worlds_bp.route('/<int:world_id>', methods=['DELETE'])
def delete_world(world_id):
    world = workspace_world(world_id)
    if not world:
        return error_response('world_not_found', 'World not found.', 404)

    force_delete = str(request.args.get('force', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    linked_campaign_rows = (
        Campaign.query.filter_by(world_id=world_id, workspace_id=current_workspace_id())
        .order_by(Campaign.created_at.asc(), Campaign.campaign_id.asc())
        .all()
    )
    linked_campaigns = len(linked_campaign_rows)
    linked_maps = Map.query.filter_by(world_id=world_id).count()
    linked_npcs = Npc.query.filter_by(world_id=world_id).count()
    if (linked_campaigns or linked_maps or linked_npcs) and not force_delete:
        return error_response(
            'world_in_use',
            'World is still used by campaigns, maps, or NPCs.',
            409,
            {
                'campaign_count': int(linked_campaigns),
                'map_count': int(linked_maps),
                'npc_count': int(linked_npcs),
                'campaigns': [
                    {
                        'campaign_id': campaign.campaign_id,
                        'title': campaign.title,
                        'status': campaign.status or 'active',
                        'is_archived': (campaign.status or 'active') == 'archived',
                    }
                    for campaign in linked_campaign_rows
                ],
            },
        )

    try:
        deleted_campaign_ids: list[int] = []
        if force_delete:
            from aidm_server.blueprints.campaigns import _force_delete_campaign

            for campaign in linked_campaign_rows:
                _force_delete_campaign(campaign)
                deleted_campaign_ids.append(campaign.campaign_id)
            Map.query.filter_by(world_id=world_id).delete(synchronize_session=False)
            Npc.query.filter_by(world_id=world_id).delete(synchronize_session=False)
        db.session.delete(world)
        db.session.commit()
        return jsonify(
            {
                'deleted': True,
                'world_id': world_id,
                'force_deleted': force_delete,
                'deleted_campaign_ids': deleted_campaign_ids,
            }
        )
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to delete world: %s', str(exc))
        return error_response('world_delete_failed', 'Failed to delete world.', 400)
