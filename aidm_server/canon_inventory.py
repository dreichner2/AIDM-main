"""Inventory extraction, validation, and mutation for emergent canon."""

from __future__ import annotations

import re

from aidm_server.canon_text import int_or_default, normalized_name, positive_int
from aidm_server.database import db
from aidm_server.models import DmTurn, Player, safe_json_dumps, safe_json_loads


ITEM_HEADWORDS = {
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
ITEM_MATERIAL_HINTS = {
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
ITEM_NAME_CONNECTORS = {'of'}
NON_ITEM_HEADWORDS = {
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
NON_ITEM_TOKENS = {
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

INVENTORY_GAIN_PATTERNS = [
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
INVENTORY_LOSS_PATTERNS = [
    re.compile(
        r'\byou\s+(?:drop|give|hand over|leave behind|discard|consume|use up|spend)\s+'
        r'(?:the|a|an|some|your)?\s*([a-z][a-z0-9\' -]{1,40}?)(?:\s+to\b|\s+on\b|[.,;!?]|$)',
        re.IGNORECASE,
    ),
]


def clean_inventory_item_name(item_name: str | None) -> str | None:
    candidate = str(item_name or '').strip(" \t\r\n'\"`")
    if not candidate:
        return None
    candidate = re.sub(r'\b(?:the|a|an|some|your|their|his|her)\b\s+', '', candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r'\s+', ' ', candidate).strip(' -')
    if not candidate:
        return None
    return candidate[:80]


def looks_like_inventory_item(item_name: str | None) -> bool:
    candidate = clean_inventory_item_name(item_name)
    if not candidate:
        return False

    normalized = normalized_name(candidate)
    tokens = normalized.split()
    if not tokens or len(tokens) > 4:
        return False

    if any(token in NON_ITEM_TOKENS for token in tokens):
        return False

    if any(token not in ITEM_NAME_CONNECTORS and len(token) <= 1 for token in tokens):
        return False

    head = tokens[-1]
    if head in NON_ITEM_HEADWORDS:
        return False

    if head in ITEM_HEADWORDS:
        return True

    if any(token in ITEM_MATERIAL_HINTS for token in tokens[:-1]) and head not in NON_ITEM_HEADWORDS:
        return True

    return False


def append_inventory_change(patch: dict, action: str, item_name: str | None, quantity: int = 1):
    clean_name = clean_inventory_item_name(item_name)
    if not clean_name or not looks_like_inventory_item(clean_name):
        return
    normalized_item = normalized_name(clean_name)
    existing = next(
        (
            change
            for change in patch['inventory_changes']
            if normalized_name(change.get('item_name')) == normalized_item and change.get('action') == action
        ),
        None,
    )
    if existing:
        existing['quantity'] = positive_int(existing.get('quantity', 1)) + positive_int(quantity)
        return

    patch['inventory_changes'].append(
        {
            'action': action,
            'item_name': clean_name,
            'quantity': positive_int(quantity),
        }
    )

    if not any(
        entity.get('entity_type') == 'item' and normalized_name(entity.get('name')) == normalized_item
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


def extract_inventory_changes_from_text(text: str, patterns: list[re.Pattern], action: str, patch: dict):
    for pattern in patterns:
        for match in pattern.finditer(text or ''):
            append_inventory_change(patch, action=action, item_name=match.group(1))


def load_inventory(raw_value: str | None) -> list[dict]:
    if not raw_value:
        return []

    payload = safe_json_loads(raw_value, None)
    if isinstance(payload, dict):
        payload = payload.get('items', [])
    if isinstance(payload, list):
        normalized_items: list[dict] = []
        for item in payload:
            if isinstance(item, dict):
                name = clean_inventory_item_name(item.get('name'))
                if not name:
                    continue
                normalized_items.append({'name': name, 'quantity': positive_int(item.get('quantity', 1))})
            elif isinstance(item, str):
                name = clean_inventory_item_name(item)
                if name:
                    normalized_items.append({'name': name, 'quantity': 1})
        return normalized_items

    if isinstance(raw_value, str):
        parts = [part.strip() for part in raw_value.split(',') if part.strip()]
        return [{'name': part, 'quantity': 1} for part in parts]
    return []


def dump_inventory(items: list[dict]) -> str:
    compacted = [
        {'name': item['name'], 'quantity': positive_int(item.get('quantity', 1))}
        for item in items
        if item.get('name') and int_or_default(item.get('quantity', 1), default=1) > 0
    ]
    return safe_json_dumps(compacted, [])


def inventory_payload(raw_value: str | None) -> list[dict]:
    return load_inventory(raw_value)


def apply_inventory_changes(turn: DmTurn, changes: list[dict]) -> list[dict]:
    if not changes:
        return []

    player = db.session.get(Player, turn.player_id)
    if not player:
        return []

    inventory = load_inventory(player.inventory)
    index = {normalized_name(item['name']): item for item in inventory}
    applied_changes: list[dict] = []

    for change in changes:
        action = change['action']
        item_name = change['item_name']
        quantity = positive_int(change.get('quantity', 1))
        key = normalized_name(item_name)
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

    player.inventory = dump_inventory([item for item in inventory if item.get('quantity', 0) > 0])
    return applied_changes
