from __future__ import annotations

from collections import Counter
from collections import defaultdict
import json
import re
from typing import Any

from sqlalchemy import func

from aidm_server.contracts import ProviderRequest
from aidm_server.database import db
from aidm_server.models import (
    Campaign,
    DmTurn,
    Player,
    SessionState,
    StoryEntity,
    StoryFact,
    StoryThread,
    TurnCanonUpdate,
    get_or_create_session_state,
    safe_json_dumps,
    safe_json_loads,
)
from aidm_server.telemetry import telemetry_event, telemetry_metric
from aidm_server.time_utils import utc_now


_LOCATION_PATTERNS = [
    re.compile(
        r'\b(?:enter|entered|arrive(?:d)? at|reach(?:ed)?|head(?:ing)? to|go(?:ing)? to|travel(?:ing)? to|'
        r'move(?:d)? to|sprint(?:ing)? for|run(?:ning)? for|escape(?:d)? (?:to|through)|'
        r'slip(?:ped)? into|leap(?:ing)? into|jump(?:ing)? into|vault(?:ing)? onto)\s+'
        r'(?:the\s+)?([^.,;!?]+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:you reach|you arrive at|you enter|you slip into|you burst into|you move into)\s+'
        r'(?:the\s+)?([^.,;!?]+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:lead(?:s|ing)?|guide(?:s|d)?|usher(?:s|ed)?|pull(?:s|ed)?)\s+you\s+'
        r'(?:into|to|toward)\s+(?:the\s+)?([^.,;!?]+)',
        re.IGNORECASE,
    ),
]

_ENTITY_RE = re.compile(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b')
_ENTITY_STOPWORDS = {
    'The',
    'This',
    'That',
    'Your',
    'You',
    'And',
    'But',
    'For',
    'With',
    'Describe',
    'Roll',
    'Smoke',
    'World',
}

_EMPTY_PATCH = {
    'entities': [],
    'facts': [],
    'threads': [],
    'inventory_changes': [],
    'projection': {},
}

_ALLOWED_FACT_CHANGE_TYPES = {'reveal', 'retcon', 'misconception', 'correction'}
_GLOBAL_SINGLETON_FACTS = {'current_location', 'current_quest'}
_SUBJECT_SINGLETON_FACTS = {'status', 'role', 'current_holder'}
_ITEM_HEADWORDS = {
    'amulet',
    'armor',
    'armour',
    'arrow',
    'arrows',
    'axe',
    'badge',
    'bag',
    'blade',
    'bone',
    'bones',
    'book',
    'bottle',
    'bow',
    'box',
    'bundle',
    'charm',
    'chain',
    'cloak',
    'coin',
    'coins',
    'component',
    'components',
    'crown',
    'crystal',
    'crystals',
    'dagger',
    'feather',
    'figurine',
    'flask',
    'gem',
    'gems',
    'hammer',
    'helmet',
    'herb',
    'herbs',
    'idol',
    'journal',
    'key',
    'keys',
    'knife',
    'lantern',
    'letter',
    'map',
    'mask',
    'medallion',
    'necklace',
    'note',
    'notes',
    'orb',
    'package',
    'parcel',
    'pendant',
    'potion',
    'pouch',
    'reagent',
    'reagents',
    'relic',
    'ring',
    'rod',
    'rope',
    'sack',
    'satchel',
    'scroll',
    'seal',
    'shield',
    'skull',
    'spear',
    'staff',
    'stone',
    'stones',
    'supplies',
    'supply',
    'sword',
    'talisman',
    'token',
    'tome',
    'torch',
    'trinket',
    'vial',
    'wand',
}
_ITEM_MATERIAL_HINTS = {
    'amber',
    'bone',
    'brass',
    'bronze',
    'cloth',
    'copper',
    'crystal',
    'glass',
    'gold',
    'iron',
    'ivory',
    'jade',
    'leather',
    'obsidian',
    'oak',
    'onyx',
    'paper',
    'rope',
    'silver',
    'steel',
    'wood',
    'wooden',
}
_ITEM_NAME_CONNECTORS = {'of'}
_NON_ITEM_HEADWORDS = {
    'advice',
    'answer',
    'attention',
    'chance',
    'choice',
    'fear',
    'glance',
    'hope',
    'look',
    'news',
    'nod',
    'path',
    'permission',
    'promise',
    'rumor',
    'silence',
    'smile',
    'stare',
    'story',
    'time',
    'trouble',
    'truth',
    'warning',
    'way',
    'word',
}
_NON_ITEM_TOKENS = {
    'across',
    'along',
    'around',
    'away',
    'before',
    'behind',
    'deeper',
    'down',
    'further',
    'immediately',
    'inside',
    'into',
    'onto',
    'outside',
    'through',
    'toward',
    'towards',
    'under',
    'within',
}

_INVENTORY_GAIN_PATTERNS = [
    re.compile(
        r'\byou\s+(?:take|pick up|pocket|claim|receive|accept|gather|loot|carry away)\s+'
        r'(?:the|a|an|some|your)?\s*([a-z][a-z0-9\' -]{1,40}?)(?:\s+from\b|[.,;!?]|$)',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b[A-Z][a-z]{2,}\s+(?:hands|gives|passes|offers)\s+you\s+'
        r'(?:the|a|an|some)?\s*([a-z][a-z0-9\' -]{1,40}?)(?:\s+with\b|[.,;!?]|$)',
        re.IGNORECASE,
    ),
]
_INVENTORY_LOSS_PATTERNS = [
    re.compile(
        r'\byou\s+(?:drop|give|hand over|leave behind|discard|consume|use up|spend)\s+'
        r'(?:the|a|an|some|your)?\s*([a-z][a-z0-9\' -]{1,40}?)(?:\s+to\b|\s+on\b|[.,;!?]|$)',
        re.IGNORECASE,
    ),
]


def _empty_patch() -> dict:
    return {
        'entities': [],
        'facts': [],
        'threads': [],
        'inventory_changes': [],
        'projection': {},
    }


def _normalize_location_candidate(raw_text: str | None) -> str | None:
    text = (raw_text or '').strip(" \t\r\n'\"`")
    if not text:
        return None

    lower = text.lower()
    split_tokens = [
        ' and ',
        ' while ',
        ' before ',
        ' after ',
        ' as ',
        ' with ',
        ' but ',
        ' where ',
        ' to ',
        ' through ',
        ' across ',
        ' above ',
        ' unhindered',
    ]
    cut = len(text)
    for token in split_tokens:
        idx = lower.find(token)
        if idx != -1 and idx < cut:
            cut = idx

    cleaned = text[:cut].strip(' -')
    words = cleaned.split()
    trailing_noise = {
        'quietly',
        'carefully',
        'quickly',
        'silently',
        'safely',
        'unseen',
        'unhindered',
        'immediately',
    }
    while words and words[-1].lower().strip('.,;:!?') in trailing_noise:
        words.pop()
    if not words:
        return None
    return ' '.join(words[:8])


def infer_location_update(player_input: str, dm_output: str | None) -> str | None:
    sources = [player_input or '', dm_output or '']
    for source in sources:
        for pattern in _LOCATION_PATTERNS:
            match = pattern.search(source)
            if not match:
                continue
            candidate = _normalize_location_candidate(match.group(1))
            if candidate:
                return candidate
    return None


def _extract_json_object(text: str) -> dict | None:
    candidate = (text or '').strip()
    if not candidate:
        return None
    try:
        loaded = json.loads(candidate)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', candidate, re.DOTALL)
    if not match:
        return None

    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _normalize_patch(raw_patch: dict | None) -> dict:
    patch = _empty_patch()
    if not isinstance(raw_patch, dict):
        return patch

    for key in ('entities', 'facts', 'threads', 'inventory_changes'):
        value = raw_patch.get(key, [])
        patch[key] = value if isinstance(value, list) else []

    projection = raw_patch.get('projection', {})
    patch['projection'] = projection if isinstance(projection, dict) else {}
    return patch


def _normalized_name(value: str | None) -> str:
    text = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()
    return re.sub(r'\s+', ' ', text)


def _int_or_default(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _positive_int(value: Any, default: int = 1) -> int:
    return max(1, _int_or_default(value, default))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_labels(entity: StoryEntity) -> set[str]:
    labels = {
        _normalized_name(entity.name),
        _normalized_name(entity.canonical_name),
    }
    aliases = safe_json_loads(entity.aliases_json, [])
    aliases = aliases if isinstance(aliases, list) else []
    labels.update(_normalized_name(alias) for alias in aliases)
    return {label for label in labels if label}


def _token_aliases(entity: StoryEntity) -> set[str]:
    aliases: set[str] = set()
    for label in _candidate_labels(entity):
        parts = label.split()
        if len(parts) > 1:
            aliases.add(parts[0])
            aliases.add(parts[-1])
    return aliases


class _EntityLookupIndex:
    def __init__(self, campaign_id: int):
        self.campaign_id = campaign_id
        self.entities_by_id: dict[int, StoryEntity] = {}
        self._exact: dict[str, set[int]] = defaultdict(set)
        self._token: dict[str, set[int]] = defaultdict(set)
        self._memberships: dict[int, tuple[set[str], set[str]]] = {}

        for entity in StoryEntity.query.filter_by(campaign_id=campaign_id).all():
            self.refresh(entity)

    def refresh(self, entity: StoryEntity):
        previous = self._memberships.pop(entity.entity_id, (set(), set()))
        previous_exact, previous_token = previous
        for label in previous_exact:
            ids = self._exact.get(label)
            if ids is not None:
                ids.discard(entity.entity_id)
                if not ids:
                    del self._exact[label]
        for token in previous_token:
            ids = self._token.get(token)
            if ids is not None:
                ids.discard(entity.entity_id)
                if not ids:
                    del self._token[token]

        exact_labels = _candidate_labels(entity)
        token_labels = _token_aliases(entity)
        self.entities_by_id[entity.entity_id] = entity
        self._memberships[entity.entity_id] = (exact_labels, token_labels)

        for label in exact_labels:
            self._exact[label].add(entity.entity_id)
        for token in token_labels:
            self._token[token].add(entity.entity_id)

    def find(self, incoming_type: str, incoming_name: str) -> StoryEntity | None:
        normalized_incoming = _normalized_name(incoming_name)
        if not normalized_incoming:
            return None

        exact_matches = [
            self.entities_by_id[entity_id]
            for entity_id in sorted(self._exact.get(normalized_incoming, set()))
            if _entity_type_matches(self.entities_by_id[entity_id].entity_type, incoming_type)
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]

        if ' ' not in normalized_incoming:
            token_matches = [
                self.entities_by_id[entity_id]
                for entity_id in sorted(self._token.get(normalized_incoming, set()))
                if _entity_type_matches(self.entities_by_id[entity_id].entity_type, incoming_type)
            ]
            if len(token_matches) == 1:
                return token_matches[0]

        return exact_matches[0] if exact_matches else None


def _entity_type_matches(existing_type: str, incoming_type: str) -> bool:
    if not incoming_type or incoming_type == 'entity':
        return True
    if existing_type == incoming_type:
        return True
    return existing_type == 'entity'


def _find_existing_entity(
    campaign_id: int,
    incoming_type: str,
    incoming_name: str,
    lookup_index: _EntityLookupIndex | None = None,
) -> StoryEntity | None:
    if lookup_index is not None:
        return lookup_index.find(incoming_type, incoming_name)
    return _EntityLookupIndex(campaign_id).find(incoming_type, incoming_name)


def _clean_inventory_item_name(item_name: str | None) -> str | None:
    candidate = str(item_name or '').strip(" \t\r\n'\"`")
    if not candidate:
        return None
    candidate = re.sub(r'\b(?:the|a|an|some|your|their|his|her)\b\s+', '', candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r'\s+', ' ', candidate).strip(' -')
    if not candidate:
        return None
    return candidate[:80]


def _looks_like_inventory_item(item_name: str | None) -> bool:
    candidate = _clean_inventory_item_name(item_name)
    if not candidate:
        return False

    normalized = _normalized_name(candidate)
    tokens = normalized.split()
    if not tokens or len(tokens) > 4:
        return False

    if any(token in _NON_ITEM_TOKENS for token in tokens):
        return False

    if any(token not in _ITEM_NAME_CONNECTORS and len(token) <= 1 for token in tokens):
        return False

    head = tokens[-1]
    if head in _NON_ITEM_HEADWORDS:
        return False

    if head in _ITEM_HEADWORDS:
        return True

    if any(token in _ITEM_MATERIAL_HINTS for token in tokens[:-1]) and head not in _NON_ITEM_HEADWORDS:
        return True

    return False


def _append_inventory_change(patch: dict, action: str, item_name: str | None, quantity: int = 1):
    clean_name = _clean_inventory_item_name(item_name)
    if not clean_name or not _looks_like_inventory_item(clean_name):
        return
    normalized_item = _normalized_name(clean_name)
    existing = next(
        (
            change
            for change in patch['inventory_changes']
            if _normalized_name(change.get('item_name')) == normalized_item and change.get('action') == action
        ),
        None,
    )
    if existing:
        existing['quantity'] = _positive_int(existing.get('quantity', 1)) + _positive_int(quantity)
        return

    patch['inventory_changes'].append(
        {
            'action': action,
            'item_name': clean_name,
            'quantity': _positive_int(quantity),
        }
    )

    if not any(
        entity.get('entity_type') == 'item' and _normalized_name(entity.get('name')) == normalized_item
        for entity in patch['entities']
    ):
        patch['entities'].append(
            {
                'entity_type': 'item',
                'name': clean_name,
                'summary': 'Explicitly involved in a deterministic inventory consequence.',
                'status': 'active',
            }
        )


def _extract_inventory_changes_from_text(text: str, patterns: list[re.Pattern], action: str, patch: dict):
    for pattern in patterns:
        for match in pattern.finditer(text or ''):
            _append_inventory_change(patch, action=action, item_name=match.group(1))


def _heuristic_patch(
    turn: DmTurn,
    campaign: Campaign,
    dm_output: str,
    speaking_player_name: str | None,
    triggered_segments: list[dict],
) -> dict:
    patch = _normalize_patch(None)
    location = infer_location_update(turn.player_input, dm_output)
    if location:
        patch['entities'].append(
            {
                'entity_type': 'location',
                'name': location,
                'summary': 'Active scene location mentioned during play.',
                'status': 'active',
            }
        )
        patch['facts'].append(
            {
                'predicate': 'current_location',
                'value_text': location,
                'confidence': 0.72,
                'replace_existing': True,
            }
        )
        patch['projection']['current_location'] = location

    candidate_names = Counter()
    source_text = f'{turn.player_input}\n{dm_output}'
    for match in _ENTITY_RE.findall(source_text):
        if match in _ENTITY_STOPWORDS:
            continue
        if speaking_player_name and match.lower() == speaking_player_name.lower():
            continue
        if match.lower() in {
            (campaign.title or '').lower(),
            (campaign.description or '').lower(),
        }:
            continue
        candidate_names[match] += 1

    for name, _count in candidate_names.most_common(6):
        patch['entities'].append(
            {
                'entity_type': 'npc',
                'name': name,
                'summary': 'Named in improvised narration.',
                'status': 'active',
            }
        )

    for segment_payload in triggered_segments:
        title = str(segment_payload.get('title') or '').strip()
        if not title:
            continue
        patch['threads'].append(
            {
                'title': title,
                'summary': f'Authored story thread activated: {title}.',
                'status': 'open',
                'priority': 2,
                'source': 'segment',
                'metadata': {
                    'segment_id': segment_payload.get('segment_id'),
                    'reason': segment_payload.get('reason'),
                },
            }
        )

    _extract_inventory_changes_from_text(dm_output or '', _INVENTORY_GAIN_PATTERNS, 'acquire', patch)
    _extract_inventory_changes_from_text(dm_output or '', _INVENTORY_LOSS_PATTERNS, 'lose', patch)

    return patch


def _extract_with_provider(
    turn: DmTurn,
    campaign: Campaign,
    dm_output: str,
    speaking_player_name: str | None,
    triggered_segments: list[dict],
) -> tuple[dict | None, str | None]:
    from aidm_server.llm import get_provider

    context = build_emergent_context(campaign.campaign_id, session_id=turn.session_id, entity_limit=8, fact_limit=12, thread_limit=8)
    provider = get_provider()

    request = ProviderRequest(
        system_message=(
            'You maintain flexible canon for an improvisational tabletop campaign. '
            'Return strict JSON only with keys entities, facts, threads, inventory_changes, projection. '
            'Do not invent beyond what became canon in this turn. '
            'Campaign segments are optional story threads, not rails.'
        ),
        prompt=(
            f'CURRENT CANON:\n{json.dumps(context, indent=2)}\n\n'
            f'PLAYER CHARACTER: {speaking_player_name or "Unknown"}\n'
            f'CAMPAIGN TITLE: {campaign.title}\n'
            f'TURN INPUT:\n{turn.player_input}\n\n'
            f'DM OUTPUT:\n{dm_output}\n\n'
            f'TRIGGERED SEGMENTS:\n{json.dumps(triggered_segments, indent=2)}\n\n'
            'Return JSON of the form:\n'
            '{'
            '"entities":[{"entity_type":"npc|location|faction|item|rumor|ritual","name":"...","canonical_name":"optional","aliases":["optional"],"summary":"...","status":"active"}],'
            '"facts":[{"predicate":"...","value_text":"...","confidence":0.0,"replace_existing":false,"change_type":"optional reveal|retcon|misconception|correction"}],'
            '"threads":[{"title":"...","summary":"...","status":"open","priority":1,"source":"emergent","metadata":{}}],'
            '"inventory_changes":[{"action":"acquire|lose","item_name":"...","quantity":1}],'
            '"projection":{"current_location":"optional"}}'
        ),
    )

    try:
        response = provider.generate(request)
    except Exception as exc:
        telemetry_event(
            'memory.extract.provider_failed',
            payload={'campaign_id': campaign.campaign_id, 'turn_id': turn.turn_id, 'error': str(exc)},
            severity='warning',
        )
        return None, None

    parsed = _extract_json_object(response.text)
    if not parsed:
        return None, response.model
    return _normalize_patch(parsed), response.model


def extract_canon_patch(
    turn: DmTurn,
    campaign: Campaign,
    dm_output: str,
    speaking_player_name: str | None,
    triggered_segments: list[dict] | None = None,
) -> tuple[dict, str]:
    triggered_segments = triggered_segments or []
    provider_patch, extractor_model = _extract_with_provider(
        turn=turn,
        campaign=campaign,
        dm_output=dm_output,
        speaking_player_name=speaking_player_name,
        triggered_segments=triggered_segments,
    )
    if provider_patch is not None:
        # Inventory consequences are deterministic fairness state; never trust
        # the model to invent them without explicit textual evidence.
        provider_patch['inventory_changes'] = []
        _extract_inventory_changes_from_text(dm_output or '', _INVENTORY_GAIN_PATTERNS, 'acquire', provider_patch)
        _extract_inventory_changes_from_text(dm_output or '', _INVENTORY_LOSS_PATTERNS, 'lose', provider_patch)
        telemetry_metric('memory.extract.provider_success_total', 1)
        return provider_patch, extractor_model or 'provider'

    telemetry_metric('memory.extract.heuristic_fallback_total', 1)
    return (
        _heuristic_patch(
            turn=turn,
            campaign=campaign,
            dm_output=dm_output,
            speaking_player_name=speaking_player_name,
            triggered_segments=triggered_segments,
        ),
        'heuristic-v1',
    )


def _merge_aliases(existing_raw: str | None, incoming: list[str] | None) -> str:
    aliases = safe_json_loads(existing_raw, [])
    aliases = aliases if isinstance(aliases, list) else []
    for alias in incoming or []:
        alias_text = str(alias or '').strip()
        if alias_text and alias_text not in aliases:
            aliases.append(alias_text)
    return safe_json_dumps(aliases, [])


def _merge_metadata(existing_raw: str | None, incoming: dict | None) -> str:
    payload = safe_json_loads(existing_raw, {})
    payload = payload if isinstance(payload, dict) else {}
    if isinstance(incoming, dict):
        payload.update(incoming)
    return safe_json_dumps(payload, {})


def _get_or_create_entity(
    campaign_id: int,
    session_id: int | None,
    turn_id: int,
    payload: dict,
    lookup_index: _EntityLookupIndex | None = None,
) -> StoryEntity | None:
    name = str(payload.get('name') or '').strip()
    if not name:
        return None

    entity_type = str(payload.get('entity_type') or 'entity').strip().lower()
    entity = _find_existing_entity(
        campaign_id=campaign_id,
        incoming_type=entity_type,
        incoming_name=name,
        lookup_index=lookup_index,
    )

    if not entity:
        entity = StoryEntity(
            campaign_id=campaign_id,
            session_id=session_id,
            entity_type=entity_type,
            name=name,
            canonical_name=payload.get('canonical_name') or name,
            summary=payload.get('summary'),
            status=payload.get('status') or 'active',
            aliases_json=safe_json_dumps(payload.get('aliases', []), []),
            metadata_json=safe_json_dumps(payload.get('metadata', {}), {}),
            first_seen_turn_id=turn_id,
            last_seen_turn_id=turn_id,
        )
        db.session.add(entity)
        db.session.flush()
        if lookup_index is not None:
            lookup_index.refresh(entity)
        return entity

    entity.session_id = entity.session_id or session_id
    entity.last_seen_turn_id = turn_id
    if entity.entity_type == 'entity' and entity_type != 'entity':
        entity.entity_type = entity_type
    if payload.get('canonical_name') and not entity.canonical_name:
        entity.canonical_name = payload.get('canonical_name')
    if payload.get('summary'):
        entity.summary = payload.get('summary')
    if payload.get('status'):
        entity.status = payload.get('status')
    aliases = list(payload.get('aliases', []) or [])
    if _normalized_name(name) not in {_normalized_name(entity.name), _normalized_name(entity.canonical_name)}:
        aliases.append(name)
    entity.aliases_json = _merge_aliases(entity.aliases_json, aliases)
    entity.metadata_json = _merge_metadata(entity.metadata_json, payload.get('metadata'))
    if lookup_index is not None:
        lookup_index.refresh(entity)
    return entity


def _resolve_entity_ref(
    campaign_id: int,
    session_id: int | None,
    turn_id: int,
    payload: Any,
    lookup_index: _EntityLookupIndex | None = None,
) -> StoryEntity | None:
    if isinstance(payload, dict):
        return _get_or_create_entity(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            payload=payload,
            lookup_index=lookup_index,
        )
    if isinstance(payload, str):
        return _get_or_create_entity(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            payload={'entity_type': 'entity', 'name': payload},
            lookup_index=lookup_index,
        )
    return None


def _mark_superseded_fact(
    campaign_id: int,
    *,
    fact_id: int | None = None,
    predicate: str | None = None,
    subject_entity_id: int | None = None,
) -> StoryFact | None:
    target_fact = None

    if fact_id is not None:
        try:
            fact_id = int(fact_id)
        except (TypeError, ValueError):
            fact_id = None
        if fact_id is not None:
            candidate = db.session.get(StoryFact, fact_id)
            if candidate and candidate.campaign_id == campaign_id and candidate.fact_status == 'accepted':
                target_fact = candidate

    if target_fact is None and predicate:
        query = StoryFact.query.filter(
            StoryFact.campaign_id == campaign_id,
            StoryFact.predicate == predicate,
            StoryFact.fact_status == 'accepted',
        )
        if predicate in _SUBJECT_SINGLETON_FACTS:
            if subject_entity_id is None:
                return None
            query = query.filter(StoryFact.subject_entity_id == subject_entity_id)
        elif predicate not in _GLOBAL_SINGLETON_FACTS:
            return None
        target_fact = query.order_by(StoryFact.fact_id.desc()).first()

    if target_fact:
        target_fact.fact_status = 'superseded'
    return target_fact


def _fact_value_signature(fact_payload: dict) -> tuple[str | None, str | None]:
    value_text = fact_payload.get('value_text')
    object_name = fact_payload.get('object')
    if isinstance(object_name, dict):
        object_name = object_name.get('name')
    if value_text is None and fact_payload.get('value_json') is not None:
        value_text = safe_json_dumps(fact_payload.get('value_json'), {})
    return (
        _normalized_name(object_name) or None,
        _normalized_name(value_text) or None,
    )


def _existing_fact_signature(fact: StoryFact) -> tuple[str | None, str | None]:
    value_text = fact.value_text
    if value_text is None and fact.value_json is not None:
        value_text = fact.value_json
    return (
        _normalized_name(fact.object_entity.name if fact.object_entity else None) or None,
        _normalized_name(value_text) or None,
    )


def _fact_subject_key(payload: dict) -> str | None:
    subject = payload.get('subject')
    if isinstance(subject, dict):
        return _normalized_name(subject.get('name'))
    if isinstance(subject, str):
        return _normalized_name(subject)
    return None


def _existing_fact_subject_key(fact: StoryFact) -> str | None:
    if fact.subject_entity is None:
        return None
    return _normalized_name(fact.subject_entity.name)


def validate_canon_patch(turn: DmTurn, campaign: Campaign, patch: dict) -> tuple[dict, list[dict]]:
    patch = _normalize_patch(patch)
    rejections: list[dict] = []

    deduped_entities: list[dict] = []
    seen_entities: set[tuple[str, str]] = set()
    for entity_payload in patch['entities']:
        name = _clean_inventory_item_name(entity_payload.get('name'))
        if not name:
            continue
        entity_type = str(entity_payload.get('entity_type') or 'entity').strip().lower()
        dedupe_key = (entity_type, _normalized_name(name))
        if dedupe_key in seen_entities:
            continue
        seen_entities.add(dedupe_key)
        normalized_payload = dict(entity_payload)
        normalized_payload['name'] = name
        normalized_payload['entity_type'] = entity_type
        deduped_entities.append(normalized_payload)
    patch['entities'] = deduped_entities

    validated_facts: list[dict] = []
    for fact_payload in patch['facts']:
        predicate = str(fact_payload.get('predicate') or '').strip()
        if not predicate:
            continue

        fact_copy = dict(fact_payload)
        fact_copy['predicate'] = predicate

        change_type = str(fact_copy.get('change_type') or '').strip().lower()
        replace_existing = bool(fact_copy.get('replace_existing'))
        incoming_signature = _fact_value_signature(fact_copy)
        subject_key = _fact_subject_key(fact_copy)

        accepted_facts = (
            StoryFact.query.filter(
                StoryFact.campaign_id == campaign.campaign_id,
                StoryFact.predicate == predicate,
                StoryFact.fact_status == 'accepted',
            )
            .order_by(StoryFact.fact_id.desc())
            .all()
        )

        conflicting_fact: StoryFact | None = None
        duplicate = False
        for existing in accepted_facts:
            existing_signature = _existing_fact_signature(existing)
            if incoming_signature == existing_signature:
                if predicate in _GLOBAL_SINGLETON_FACTS or (
                    predicate in _SUBJECT_SINGLETON_FACTS and subject_key == _existing_fact_subject_key(existing)
                ):
                    duplicate = True
                    break
                continue

            if predicate in _GLOBAL_SINGLETON_FACTS:
                conflicting_fact = existing
                break

            if predicate in _SUBJECT_SINGLETON_FACTS and subject_key and subject_key == _existing_fact_subject_key(existing):
                conflicting_fact = existing
                break

        if duplicate:
            continue

        if conflicting_fact and not replace_existing and change_type not in _ALLOWED_FACT_CHANGE_TYPES:
            rejections.append(
                {
                    'type': 'fact_conflict',
                    'predicate': predicate,
                    'subject': subject_key,
                    'existing_fact_id': conflicting_fact.fact_id,
                    'reason': 'conflicting accepted fact without explicit change_type or replace_existing',
                }
            )
            continue

        if conflicting_fact and (replace_existing or change_type in _ALLOWED_FACT_CHANGE_TYPES):
            fact_copy['replace_existing'] = True
            fact_copy['supersedes_fact_id'] = conflicting_fact.fact_id

        validated_facts.append(fact_copy)

    patch['facts'] = validated_facts

    validated_inventory_changes: list[dict] = []
    for change in patch['inventory_changes']:
        action = str(change.get('action') or '').strip().lower()
        if action not in {'acquire', 'lose'}:
            continue
        item_name = _clean_inventory_item_name(change.get('item_name'))
        if not item_name:
            continue
        if not _looks_like_inventory_item(item_name):
            rejections.append(
                {
                    'type': 'inventory_change_rejected',
                    'action': action,
                    'item_name': item_name,
                    'reason': 'inventory changes must reference a tangible item',
                }
            )
            continue
        validated_inventory_changes.append(
            {
                'action': action,
                'item_name': item_name,
                'quantity': _positive_int(change.get('quantity', 1)),
            }
        )
    patch['inventory_changes'] = validated_inventory_changes

    return patch, rejections


def _load_inventory(raw_value: str | None) -> list[dict]:
    if not raw_value:
        return []

    payload = safe_json_loads(raw_value, None)
    if isinstance(payload, dict):
        payload = payload.get('items', [])
    if isinstance(payload, list):
        normalized_items: list[dict] = []
        for item in payload:
            if isinstance(item, dict):
                name = _clean_inventory_item_name(item.get('name'))
                if not name:
                    continue
                normalized_items.append({'name': name, 'quantity': _positive_int(item.get('quantity', 1))})
            elif isinstance(item, str):
                name = _clean_inventory_item_name(item)
                if name:
                    normalized_items.append({'name': name, 'quantity': 1})
        return normalized_items

    if isinstance(raw_value, str):
        parts = [part.strip() for part in raw_value.split(',') if part.strip()]
        return [{'name': part, 'quantity': 1} for part in parts]
    return []


def _dump_inventory(items: list[dict]) -> str:
    compacted = [
        {'name': item['name'], 'quantity': _positive_int(item.get('quantity', 1))}
        for item in items
        if item.get('name') and _int_or_default(item.get('quantity', 1), default=1) > 0
    ]
    return safe_json_dumps(compacted, [])


def inventory_payload(raw_value: str | None) -> list[dict]:
    return _load_inventory(raw_value)


def _apply_inventory_changes(turn: DmTurn, changes: list[dict]) -> list[dict]:
    if not changes:
        return []

    player = db.session.get(Player, turn.player_id)
    if not player:
        return []

    inventory = _load_inventory(player.inventory)
    index = {_normalized_name(item['name']): item for item in inventory}
    applied_changes: list[dict] = []

    for change in changes:
        action = change['action']
        item_name = change['item_name']
        quantity = _positive_int(change.get('quantity', 1))
        key = _normalized_name(item_name)
        item_entry = index.get(key)

        if action == 'acquire':
            if item_entry:
                item_entry['quantity'] += quantity
            else:
                item_entry = {'name': item_name, 'quantity': quantity}
                inventory.append(item_entry)
                index[key] = item_entry
            applied_changes.append({'action': action, 'item_name': item_name, 'quantity': quantity})
            continue

        if action == 'lose' and item_entry:
            item_entry['quantity'] -= quantity
            applied_changes.append({'action': action, 'item_name': item_name, 'quantity': quantity})

    player.inventory = _dump_inventory([item for item in inventory if item.get('quantity', 0) > 0])
    return applied_changes


def apply_canon_patch(
    turn: DmTurn,
    campaign: Campaign,
    patch: dict,
    extractor_model: str,
    rejections: list[dict] | None = None,
) -> dict:
    patch = _normalize_patch(patch)
    rejections = rejections or []
    update_record = TurnCanonUpdate(
        turn_id=turn.turn_id,
        campaign_id=campaign.campaign_id,
        raw_patch_json=safe_json_dumps(patch, _EMPTY_PATCH),
        status='applied_with_rejections' if rejections else 'applied',
        extractor_model=extractor_model,
        error_text=(safe_json_dumps(rejections, []) if rejections else None),
    )
    db.session.add(update_record)
    db.session.flush()

    applied_summary = {
        'entities_created_or_updated': [],
        'facts_created': 0,
        'threads_created_or_updated': [],
        'inventory_changes_applied': [],
        'rejections': rejections,
    }
    lookup_index = _EntityLookupIndex(campaign.campaign_id)

    for entity_payload in patch['entities']:
        entity = _get_or_create_entity(
            campaign_id=campaign.campaign_id,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            payload=entity_payload,
            lookup_index=lookup_index,
        )
        if not entity:
            continue
        applied_summary['entities_created_or_updated'].append(
            {
                'entity_id': entity.entity_id,
                'entity_type': entity.entity_type,
                'name': entity.name,
            }
        )

    for fact_payload in patch['facts']:
        predicate = str(fact_payload.get('predicate') or '').strip()
        if not predicate:
            continue

        subject = _resolve_entity_ref(
            campaign.campaign_id,
            turn.session_id,
            turn.turn_id,
            fact_payload.get('subject'),
            lookup_index=lookup_index,
        )
        object_entity = _resolve_entity_ref(
            campaign.campaign_id,
            turn.session_id,
            turn.turn_id,
            fact_payload.get('object'),
            lookup_index=lookup_index,
        )

        superseded_fact = None
        if fact_payload.get('replace_existing'):
            superseded_fact = _mark_superseded_fact(
                campaign.campaign_id,
                fact_id=fact_payload.get('supersedes_fact_id'),
                predicate=predicate,
                subject_entity_id=subject.entity_id if subject else None,
            )

        fact = StoryFact(
            campaign_id=campaign.campaign_id,
            subject_entity_id=subject.entity_id if subject else None,
            predicate=predicate,
            object_entity_id=object_entity.entity_id if object_entity else None,
            value_text=fact_payload.get('value_text'),
            value_json=safe_json_dumps(fact_payload.get('value_json'), {}) if fact_payload.get('value_json') is not None else None,
            fact_status=fact_payload.get('fact_status') or 'accepted',
            confidence=_optional_float(fact_payload.get('confidence')),
            source_turn_id=turn.turn_id,
            supersedes_fact_id=superseded_fact.fact_id if superseded_fact else None,
        )
        db.session.add(fact)
        applied_summary['facts_created'] += 1

    for thread_payload in patch['threads']:
        title = str(thread_payload.get('title') or '').strip()
        if not title:
            continue

        thread = (
            StoryThread.query.filter(
                StoryThread.campaign_id == campaign.campaign_id,
                func.lower(StoryThread.title) == title.lower(),
            )
            .order_by(StoryThread.thread_id.asc())
            .first()
        )
        if not thread:
            thread = StoryThread(
                campaign_id=campaign.campaign_id,
                title=title,
                summary=thread_payload.get('summary'),
                status=thread_payload.get('status') or 'open',
                priority=_positive_int(thread_payload.get('priority', 1)),
                origin_turn_id=turn.turn_id,
                last_touched_turn_id=turn.turn_id,
                resolved_turn_id=turn.turn_id if thread_payload.get('status') == 'resolved' else None,
                source=thread_payload.get('source') or 'emergent',
                metadata_json=safe_json_dumps(thread_payload.get('metadata', {}), {}),
            )
            db.session.add(thread)
            db.session.flush()
        else:
            if thread_payload.get('summary'):
                thread.summary = thread_payload.get('summary')
            if thread_payload.get('status'):
                thread.status = thread_payload.get('status')
            if thread_payload.get('priority') is not None:
                thread.priority = _positive_int(thread_payload.get('priority'))
            thread.last_touched_turn_id = turn.turn_id
            if thread_payload.get('status') == 'resolved':
                thread.resolved_turn_id = turn.turn_id
            if thread_payload.get('source'):
                thread.source = thread_payload.get('source')
            thread.metadata_json = _merge_metadata(thread.metadata_json, thread_payload.get('metadata'))

        applied_summary['threads_created_or_updated'].append(
            {
                'thread_id': thread.thread_id,
                'title': thread.title,
                'status': thread.status,
                'source': thread.source,
            }
        )

    applied_summary['inventory_changes_applied'] = _apply_inventory_changes(turn, patch['inventory_changes'])

    update_record.applied_patch_json = safe_json_dumps(applied_summary, {})
    return applied_summary


def append_session_memory(turn: DmTurn):
    state = get_or_create_session_state(turn.session_id, turn.campaign)
    memory_snippets = safe_json_loads(state.memory_snippets, [])
    memory_snippets = memory_snippets if isinstance(memory_snippets, list) else []
    memory_snippets.append(
        {
            'turn_id': turn.turn_id,
            'player_input': turn.player_input[:250],
            'dm_output': (turn.dm_output or '')[:350],
            'requires_roll': turn.requires_roll,
            'rule_type': turn.rule_type,
            'confidence': turn.confidence,
            'roll_value': turn.roll_value,
            'outcome_status': turn.outcome_status,
            'created_at': utc_now().isoformat(),
        }
    )
    state.memory_snippets = safe_json_dumps(memory_snippets[-12:], [])

    existing_summary = (state.rolling_summary or '').strip()
    next_line = f"T{turn.turn_id} | P{turn.player_id}: {turn.player_input[:160]} | DM: {(turn.dm_output or '')[:220]}"
    state.rolling_summary = f"{existing_summary}\n{next_line}".strip()[-8000:]
    state.updated_at = utc_now()
    return state


def _latest_location_fact(campaign_id: int) -> StoryFact | None:
    return (
        StoryFact.query.filter(
            StoryFact.campaign_id == campaign_id,
            StoryFact.predicate == 'current_location',
            StoryFact.fact_status == 'accepted',
        )
        .order_by(StoryFact.fact_id.desc())
        .first()
    )


def refresh_session_projection(session_id: int, campaign: Campaign, triggered_segments: list[dict] | None = None):
    triggered_segments = triggered_segments or []
    state = get_or_create_session_state(session_id, campaign)

    location_fact = _latest_location_fact(campaign.campaign_id)
    if location_fact and location_fact.value_text:
        state.current_location = location_fact.value_text
    elif not state.current_location:
        state.current_location = campaign.location

    open_threads = (
        StoryThread.query.filter(
            StoryThread.campaign_id == campaign.campaign_id,
            StoryThread.status.in_(('open', 'active')),
        )
        .order_by(StoryThread.priority.desc(), StoryThread.updated_at.desc(), StoryThread.thread_id.desc())
        .limit(3)
        .all()
    )
    if open_threads:
        state.current_quest = ' | '.join(thread.title for thread in open_threads)
    else:
        state.current_quest = campaign.current_quest

    active_segments = safe_json_loads(state.active_segments, [])
    active_segments = active_segments if isinstance(active_segments, list) else []
    for segment_payload in triggered_segments:
        if not any(existing.get('segment_id') == segment_payload.get('segment_id') for existing in active_segments):
            active_segments.append(segment_payload)
    state.active_segments = safe_json_dumps(active_segments, [])
    state.updated_at = utc_now()
    return state


_RETRIEVAL_STOPWORDS = {
    'a',
    'an',
    'and',
    'at',
    'for',
    'from',
    'into',
    'is',
    'of',
    'on',
    'or',
    'the',
    'to',
    'with',
}


def _retrieval_tokens(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = _normalized_name(value)
        if not normalized:
            continue
        for token in normalized.split():
            if len(token) < 3 or token in _RETRIEVAL_STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def _recent_signal_text(recent_turns: list[dict] | None) -> str:
    if not recent_turns:
        return ''
    fragments: list[str] = []
    for turn in recent_turns[-3:]:
        if not isinstance(turn, dict):
            continue
        player_input = str(turn.get('player_input') or '').strip()
        dm_output = str(turn.get('dm_output') or '').strip()
        if player_input:
            fragments.append(player_input)
        if dm_output:
            fragments.append(dm_output[:160])
    return '\n'.join(fragments)


def _entity_retrieval_score(
    entity: StoryEntity,
    *,
    signal_text: str,
    signal_tokens: set[str],
    session_id: int | None,
) -> float:
    score = 0.0
    labels = _candidate_labels(entity)
    if signal_text:
        for label in labels:
            if label and label in signal_text:
                score += 10.0
    for label in labels:
        overlap = len(set(label.split()) & signal_tokens)
        if overlap:
            score += overlap * 3.0
    summary_tokens = _retrieval_tokens(entity.summary)
    summary_overlap = len(summary_tokens & signal_tokens)
    if summary_overlap:
        score += summary_overlap * 1.5
    if session_id is not None and entity.session_id == session_id:
        score += 1.0
    if str(entity.status or '').lower() in {'active', 'open'}:
        score += 0.5
    return score


def _fact_retrieval_score(
    fact: StoryFact,
    *,
    signal_text: str,
    signal_tokens: set[str],
    relevant_entity_ids: set[int],
) -> float:
    score = 0.0
    if fact.subject_entity_id in relevant_entity_ids:
        score += 5.0
    if fact.object_entity_id in relevant_entity_ids:
        score += 4.0
    if fact.predicate in _GLOBAL_SINGLETON_FACTS:
        score += 2.5

    predicate_tokens = _retrieval_tokens(fact.predicate)
    value_tokens = _retrieval_tokens(fact.value_text)
    score += len(predicate_tokens & signal_tokens) * 2.0
    score += len(value_tokens & signal_tokens) * 1.0

    subject_name = fact.subject_entity.name if fact.subject_entity else None
    object_name = fact.object_entity.name if fact.object_entity else None
    for name in (subject_name, object_name):
        normalized = _normalized_name(name)
        if normalized and normalized in signal_text:
            score += 3.0
    return score


def _thread_retrieval_score(thread: StoryThread, *, signal_text: str, signal_tokens: set[str]) -> float:
    score = float(thread.priority or 0)
    if str(thread.status or '').lower() in {'open', 'active'}:
        score += 2.0
    title_tokens = _retrieval_tokens(thread.title)
    summary_tokens = _retrieval_tokens(thread.summary)
    score += len(title_tokens & signal_tokens) * 2.5
    score += len(summary_tokens & signal_tokens) * 1.0
    normalized_title = _normalized_name(thread.title)
    if normalized_title and normalized_title in signal_text:
        score += 4.0
    return score


def build_emergent_context(
    campaign_id: int,
    session_id: int | None = None,
    entity_limit: int = 12,
    fact_limit: int = 20,
    thread_limit: int = 8,
    query_text: str | None = None,
    current_location: str | None = None,
    current_quest: str | None = None,
    recent_turns: list[dict] | None = None,
) -> dict:
    signal_text = _normalized_name(
        ' '.join(
            part
            for part in [
                query_text or '',
                current_location or '',
                current_quest or '',
                _recent_signal_text(recent_turns),
            ]
            if part
        )
    )
    signal_tokens = _retrieval_tokens(query_text, current_location, current_quest, _recent_signal_text(recent_turns))

    all_entities = StoryEntity.query.filter_by(campaign_id=campaign_id).all()
    ranked_entities = sorted(
        all_entities,
        key=lambda entity: (
            _entity_retrieval_score(entity, signal_text=signal_text, signal_tokens=signal_tokens, session_id=session_id),
            entity.updated_at or entity.created_at,
            entity.entity_id,
        ),
        reverse=True,
    )
    entities = ranked_entities[:entity_limit]
    relevant_entity_ids = {entity.entity_id for entity in entities}

    all_facts = (
        StoryFact.query.filter(
            StoryFact.campaign_id == campaign_id,
            StoryFact.fact_status == 'accepted',
        )
        .all()
    )
    ranked_facts = sorted(
        all_facts,
        key=lambda fact: (
            _fact_retrieval_score(
                fact,
                signal_text=signal_text,
                signal_tokens=signal_tokens,
                relevant_entity_ids=relevant_entity_ids,
            ),
            fact.fact_id,
        ),
        reverse=True,
    )
    if ranked_facts and _fact_retrieval_score(
        ranked_facts[0],
        signal_text=signal_text,
        signal_tokens=signal_tokens,
        relevant_entity_ids=relevant_entity_ids,
    ) <= 0.0:
        ranked_facts = sorted(all_facts, key=lambda fact: fact.fact_id, reverse=True)
    facts = ranked_facts[:fact_limit]

    all_threads = StoryThread.query.filter_by(campaign_id=campaign_id).all()
    ranked_threads = sorted(
        all_threads,
        key=lambda thread: (
            _thread_retrieval_score(thread, signal_text=signal_text, signal_tokens=signal_tokens),
            thread.updated_at or thread.created_at,
            thread.thread_id,
        ),
        reverse=True,
    )
    threads = ranked_threads[:thread_limit]

    payload = {
        'entities': [
            {
                'entity_id': entity.entity_id,
                'entity_type': entity.entity_type,
                'name': entity.name,
                'canonical_name': entity.canonical_name,
                'aliases': safe_json_loads(entity.aliases_json, []),
                'summary': entity.summary,
                'status': entity.status,
            }
            for entity in entities
        ],
        'facts': [
            {
                'fact_id': fact.fact_id,
                'subject': fact.subject_entity.name if fact.subject_entity else None,
                'predicate': fact.predicate,
                'object': fact.object_entity.name if fact.object_entity else None,
                'value_text': fact.value_text,
                'confidence': fact.confidence,
            }
            for fact in facts
        ],
        'threads': [
            {
                'thread_id': thread.thread_id,
                'title': thread.title,
                'summary': thread.summary,
                'status': thread.status,
                'priority': thread.priority,
                'source': thread.source,
            }
            for thread in threads
        ],
    }

    if session_id:
        state = SessionState.query.filter_by(session_id=session_id).first()
        payload['projection'] = {
            'current_location': state.current_location if state else None,
            'current_quest': state.current_quest if state else None,
            'rolling_summary': state.rolling_summary if state else '',
        }

    return payload
