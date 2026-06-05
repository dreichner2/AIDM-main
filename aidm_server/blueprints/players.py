from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from aidm_server.database import db
from aidm_server.emergent_memory import inventory_payload
from aidm_server.errors import error_response
from aidm_server.models import Campaign, Player, safe_json_dumps, safe_json_loads
from aidm_server.validation import coerce_int, missing_fields, parse_json_body


logger = logging.getLogger(__name__)
players_bp = Blueprint('players', __name__)


def _optional_text(value, *, max_length: int, field: str):
    if value is None:
        return '', None
    text = str(value).strip()
    if len(text) > max_length:
        return None, f'{field} must be {max_length} characters or fewer.'
    return text, None


def _required_text(value, *, max_length: int, field: str):
    text, error = _optional_text(value, max_length=max_length, field=field)
    if error:
        return None, error
    if not text:
        return None, f'{field} is required.'
    return text, None


def _structured_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return safe_json_dumps(value, {})


def _structured_payload(raw_value):
    return safe_json_loads(raw_value, raw_value)


def _player_summary_payload(player: Player) -> dict:
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


def _player_detail_payload(player: Player) -> dict:
    return {
        **_player_summary_payload(player),
        'stats': _structured_payload(player.stats),
        'inventory': inventory_payload(player.inventory),
        'character_sheet': _structured_payload(player.character_sheet),
    }


@players_bp.route('/campaigns/<int:campaign_id>/players', methods=['GET', 'POST'])
def handle_players(campaign_id):
    if request.method == 'POST':
        return add_player(campaign_id)
    return get_players(campaign_id)


def add_player(campaign_id):
    payload = parse_json_body(request)
    required = missing_fields(payload, ['name', 'character_name'])
    if required:
        return error_response('validation_error', 'Missing required fields.', 400, {'missing_fields': required})

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    name, name_error = _required_text(payload.get('name'), max_length=80, field='name')
    if name_error:
        return error_response('validation_error', name_error, 400)
    character_name, character_name_error = _required_text(
        payload.get('character_name'),
        max_length=80,
        field='character_name',
    )
    if character_name_error:
        return error_response('validation_error', character_name_error, 400)
    race, race_error = _optional_text(payload.get('race', ''), max_length=80, field='race')
    if race_error:
        return error_response('validation_error', race_error, 400)
    class_name, class_error = _optional_text(
        payload.get('char_class', payload.get('class_', '')),
        max_length=80,
        field='class',
    )
    if class_error:
        return error_response('validation_error', class_error, 400)
    level = coerce_int(payload.get('level'), 1)
    if level is None or level < 1 or level > 20:
        return error_response('validation_error', 'level must be an integer from 1 to 20.', 400)

    try:
        raw_inventory = payload.get('inventory')
        new_player = Player(
            campaign_id=campaign_id,
            name=name,
            character_name=character_name,
            race=race,
            class_=class_name,
            level=level,
            stats=_structured_text(payload.get('stats')),
            inventory=(safe_json_dumps(inventory_payload(raw_inventory), []) if raw_inventory is not None else None),
            character_sheet=_structured_text(payload.get('character_sheet')),
        )
        db.session.add(new_player)
        db.session.commit()
        return jsonify({'player_id': new_player.player_id, 'message': 'Player successfully created'}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to create player: %s', str(exc))
        return error_response('player_create_failed', 'Failed to create player.', 400)


def get_players(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return error_response('campaign_not_found', 'Campaign not found.', 404)

    players = Player.query.filter_by(campaign_id=campaign_id).all()
    return jsonify([_player_summary_payload(player) for player in players])


@players_bp.route('/<int:player_id>', methods=['GET'])
def get_player_by_id(player_id):
    player = db.session.get(Player, player_id)
    if not player:
        return error_response('player_not_found', 'Player not found.', 404)

    return jsonify(_player_detail_payload(player))


@players_bp.route('/<int:player_id>', methods=['PATCH'])
def update_player(player_id):
    payload = parse_json_body(request)
    if payload is None:
        return error_response('validation_error', 'Expected JSON request body.', 400)

    player = db.session.get(Player, player_id)
    if not player:
        return error_response('player_not_found', 'Player not found.', 404)

    text_fields = {
        'name': (80, True),
        'character_name': (80, True),
        'race': (80, False),
    }
    try:
        for field, (max_length, required) in text_fields.items():
            if field not in payload:
                continue
            if required:
                value, error = _required_text(payload.get(field), max_length=max_length, field=field)
            else:
                value, error = _optional_text(payload.get(field), max_length=max_length, field=field)
            if error:
                return error_response('validation_error', error, 400)
            setattr(player, field, value)

        if 'class_' in payload or 'char_class' in payload:
            value, error = _optional_text(
                payload.get('char_class', payload.get('class_')),
                max_length=80,
                field='class',
            )
            if error:
                return error_response('validation_error', error, 400)
            player.class_ = value

        if 'level' in payload:
            level = coerce_int(payload.get('level'))
            if level is None or level < 1 or level > 20:
                return error_response('validation_error', 'level must be an integer from 1 to 20.', 400)
            player.level = level

        if 'stats' in payload:
            player.stats = _structured_text(payload.get('stats'))
        if 'character_sheet' in payload:
            player.character_sheet = _structured_text(payload.get('character_sheet'))
        if 'inventory' in payload:
            player.inventory = safe_json_dumps(inventory_payload(payload.get('inventory')), [])

        db.session.commit()
        return jsonify(_player_detail_payload(player))
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to update player: %s', str(exc))
        return error_response('player_update_failed', 'Failed to update player.', 400)
