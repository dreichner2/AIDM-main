"""Versioned prompt templates for model-facing requests."""

from __future__ import annotations

import json
from typing import Any

from aidm_server.contracts import ProviderRequest

PROMPT_TEMPLATE_VERSION = 'v1'

DM_SYSTEM_MESSAGE = (
    'You are a narrative-first Dungeons & Dragons Dungeon Master. '
    'Maintain immersion, keep continuity, and honor existing campaign context. '
    'Treat emergent_memory and story_threads as canon that arose through play. '
    'Treat authored_segments as optional prompts, not rails or hard boundaries on creativity. '
    'Follow RULES_HINT strictly when present. '
    'If RULES_HINT.requires_roll is false and pending_checks is empty, do not request a new roll. '
    'If RULES_HINT.resolved_turn_id is set with a roll_value, treat that pending check as resolved and advance the scene. '
    'If an action warrants a roll, request a roll and defer final outcomes until a roll result arrives. '
    'Never contradict established state unless you explain a plausible in-world reason.'
)

CANON_EXTRACTION_SYSTEM_MESSAGE = (
    'You maintain flexible canon for an improvisational tabletop campaign. '
    'Return strict JSON only with keys entities, facts, threads, inventory_changes, projection. '
    'Do not invent beyond what became canon in this turn. '
    'Campaign segments are optional story threads, not rails.'
)

CANON_EXTRACTION_RESPONSE_SCHEMA = (
    '{'
    '"entities":[{"entity_type":"npc|location|faction|item|rumor|ritual","name":"...","canonical_name":"optional","aliases":["optional"],"summary":"...","status":"active"}],'
    '"facts":[{"predicate":"...","value_text":"...","confidence":0.0,"replace_existing":false,"change_type":"optional reveal|retcon|misconception|correction"}],'
    '"threads":[{"title":"...","summary":"...","status":"open","priority":1,"source":"emergent","metadata":{}}],'
    '"inventory_changes":[{"action":"acquire|lose","item_name":"...","quantity":1}],'
    '"projection":{"current_location":"optional"}}'
)


def build_dm_generate_request(user_input: str, context: str, rules_hint: dict | None = None) -> ProviderRequest:
    rules_hint_section = ''
    if rules_hint:
        rules_hint_section = f"\n\nRULES_HINT:\n{json.dumps(rules_hint)}\n"
    return ProviderRequest(
        prompt=f'CONTEXT:\n{context}\n{rules_hint_section}\nPLAYER ACTION:\n{user_input}\n',
        system_message=DM_SYSTEM_MESSAGE,
    )


def build_dm_stream_request(
    user_input: str,
    context: str,
    *,
    speaking_player: dict | None = None,
    rules_hint: dict | None = None,
) -> ProviderRequest:
    speaker_text = ''
    if speaking_player:
        speaker_text = (
            f"\nCurrent speaker: {speaking_player.get('character_name')} "
            f"(ID: {speaking_player.get('player_id')})."
        )
    rules_hint_text = ''
    if rules_hint:
        rules_hint_text = f'\nRULES_HINT:\n{json.dumps(rules_hint)}\n'

    return ProviderRequest(
        prompt=(
            f'{speaker_text}\n'
            f'CONTEXT:\n{context}\n\n'
            f'{rules_hint_text}'
            f'PLAYER INPUT:\n{user_input}\n'
        ),
        system_message=DM_SYSTEM_MESSAGE,
    )


def build_canon_extraction_request(
    *,
    context: dict[str, Any],
    campaign_title: str,
    player_input: str,
    dm_output: str,
    speaking_player_name: str | None,
    triggered_segments: list[dict],
) -> ProviderRequest:
    return ProviderRequest(
        system_message=CANON_EXTRACTION_SYSTEM_MESSAGE,
        prompt=(
            f'CURRENT CANON:\n{json.dumps(context, indent=2)}\n\n'
            f'PLAYER CHARACTER: {speaking_player_name or "Unknown"}\n'
            f'CAMPAIGN TITLE: {campaign_title}\n'
            f'TURN INPUT:\n{player_input}\n\n'
            f'DM OUTPUT:\n{dm_output}\n\n'
            f'TRIGGERED SEGMENTS:\n{json.dumps(triggered_segments, indent=2)}\n\n'
            'Return JSON of the form:\n'
            f'{CANON_EXTRACTION_RESPONSE_SCHEMA}'
        ),
    )
