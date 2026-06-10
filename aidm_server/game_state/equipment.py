from __future__ import annotations

import re
from typing import Any


HAND_SLOTS = {'main_hand', 'off_hand', 'two_hands'}
WEAPON_SLOTS = HAND_SLOTS
SHIELD_SLOT = 'off_hand'
ARMOR_SLOTS = {
    'helmet',
    'hood',
    'body_armor',
    'clothing',
    'underwear',
    'cloak',
    'hands',
    'feet',
    'belt',
    'amulet',
}
EQUIPMENT_SLOTS = HAND_SLOTS | ARMOR_SLOTS
TWO_HANDED_TERMS = {
    'two handed',
    'two hand',
    'greatsword',
    'great sword',
    'greataxe',
    'great axe',
    'greatclub',
    'great club',
    'maul',
    'longbow',
    'shortbow',
    'heavy crossbow',
    'halberd',
    'glaive',
    'pike',
}
ONE_HANDED_WEAPON_TERMS = {
    'axe',
    'battle axe',
    'battleaxe',
    'blade',
    'club',
    'dagger',
    'flail',
    'hand axe',
    'handaxe',
    'hammer',
    'javelin',
    'knife',
    'lance',
    'longsword',
    'mace',
    'morningstar',
    'quarterstaff',
    'rapier',
    'scimitar',
    'shortsword',
    'sickle',
    'sling',
    'spear',
    'staff',
    'sword',
    'trident',
    'war pick',
    'warhammer',
    'whip',
}
WEAPON_NAME_TERMS = TWO_HANDED_TERMS | ONE_HANDED_WEAPON_TERMS


def normalize_item_name(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip().lower().replace('_', ' ').replace('-', ' '))


def _labels(item: dict[str, Any]) -> set[str]:
    labels = {
        normalize_item_name(item.get('name')),
        normalize_item_name(item.get('type')),
        normalize_item_name(item.get('subtype')),
        normalize_item_name(item.get('slot')),
        normalize_item_name(item.get('equipmentSlot') or item.get('equipment_slot')),
        normalize_item_name(item.get('hands')),
    }
    for key in ('aliases', 'tags'):
        if isinstance(item.get(key), list):
            labels.update(normalize_item_name(value) for value in item[key])
    metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
    labels.update(
        normalize_item_name(metadata.get(key))
        for key in ('slot', 'equipmentSlot', 'equipment_slot', 'hands')
    )
    return {label for label in labels if label}


def _explicit_slot(value: Any) -> str | None:
    normalized = normalize_item_name(value)
    aliases = {
        'main': 'main_hand',
        'main hand': 'main_hand',
        'primary hand': 'main_hand',
        'weapon hand': 'main_hand',
        'off': 'off_hand',
        'off hand': 'off_hand',
        'secondary hand': 'off_hand',
        'shield': 'off_hand',
        'two hand': 'two_hands',
        'two hands': 'two_hands',
        'two handed': 'two_hands',
        'both hands': 'two_hands',
        'head': 'helmet',
        'helm': 'helmet',
        'helmet': 'helmet',
        'hood': 'hood',
        'body': 'body_armor',
        'torso': 'body_armor',
        'chest': 'body_armor',
        'vest': 'body_armor',
        'armor': 'body_armor',
        'armour': 'body_armor',
        'clothes': 'clothing',
        'clothing': 'clothing',
        'underclothes': 'underwear',
        'underwear': 'underwear',
        'cloak': 'cloak',
        'cape': 'cloak',
        'gloves': 'hands',
        'gauntlets': 'hands',
        'boots': 'feet',
        'shoes': 'feet',
        'belt': 'belt',
        'amulet': 'amulet',
        'necklace': 'amulet',
    }
    return aliases.get(normalized)


def is_two_handed_weapon(item: dict[str, Any]) -> bool:
    labels = _labels(item)
    return any(term in labels or term in normalize_item_name(item.get('name')) for term in TWO_HANDED_TERMS)


def is_weapon(item: dict[str, Any]) -> bool:
    labels = _labels(item)
    name = normalize_item_name(item.get('name'))
    return 'weapon' in labels or any(term in labels or term in name for term in WEAPON_NAME_TERMS)


def infer_equipment_slot(
    item: dict[str, Any],
    *,
    requested_slot: Any = None,
    equipped_items: list[dict[str, Any]] | None = None,
) -> str | None:
    requested = _explicit_slot(requested_slot)
    if requested:
        return requested

    labels = _labels(item)
    name = normalize_item_name(item.get('name'))
    stored_slot = _explicit_slot(item.get('slot') or item.get('equipmentSlot') or item.get('equipment_slot'))
    if stored_slot and stored_slot in EQUIPMENT_SLOTS:
        return stored_slot

    if is_weapon(item):
        if is_two_handed_weapon(item):
            return 'two_hands'
        equipped_items = equipped_items or []
        occupied = set()
        for equipped_item in equipped_items:
            if equipped_item is item or not equipped_item.get('equipped'):
                continue
            occupied.update(occupied_slots(equipped_item))
        if 'main_hand' not in occupied:
            return 'main_hand'
        if 'off_hand' not in occupied:
            return 'off_hand'
        return 'main_hand'

    if 'shield' in labels or 'shield' in name:
        return SHIELD_SLOT
    if 'helmet' in labels or 'helm' in labels or 'helmet' in name or 'helm' in name:
        return 'helmet'
    if 'hood' in labels or 'cowl' in labels or 'hood' in name or 'cowl' in name:
        return 'hood'
    if 'underwear' in labels or 'underclothes' in labels or 'undergarment' in labels or 'underwear' in name:
        return 'underwear'
    if 'cloak' in labels or 'cape' in labels or 'cloak' in name or 'cape' in name:
        return 'cloak'
    if 'glove' in name or 'gauntlet' in name:
        return 'hands'
    if 'boot' in name or 'shoe' in name:
        return 'feet'
    if 'belt' in labels or 'belt' in name:
        return 'belt'
    if 'amulet' in labels or 'necklace' in labels or 'amulet' in name or 'necklace' in name:
        return 'amulet'
    if (
        'armor' in labels
        or 'armour' in labels
        or 'mail' in labels
        or 'armor' in name
        or 'armour' in name
        or 'mail' in name
        or 'breastplate' in name
        or 'cuirass' in name
        or 'vest' in name
    ):
        return 'body_armor'
    if (
        'clothing' in labels
        or 'clothes' in labels
        or 'shirt' in name
        or 'tunic' in name
        or 'robe' in name
        or 'dress' in name
        or 'pants' in name
        or 'trousers' in name
    ):
        return 'clothing'
    return None


def occupied_slots(item: dict[str, Any]) -> set[str]:
    slot = infer_equipment_slot(item)
    if slot == 'two_hands':
        return {'main_hand', 'off_hand', 'two_hands'}
    if slot in {'main_hand', 'off_hand'}:
        return {slot}
    if slot:
        return {slot}
    return set()


def conflict_items(items: list[dict[str, Any]], item: dict[str, Any], slot: str) -> list[dict[str, Any]]:
    target_slots = {'main_hand', 'off_hand', 'two_hands'} if slot == 'two_hands' else {slot}
    if slot in {'main_hand', 'off_hand'}:
        target_slots.add('two_hands')
    conflicts = []
    for candidate in items:
        if candidate is item or str(candidate.get('id')) == str(item.get('id')):
            continue
        if not candidate.get('equipped'):
            continue
        if occupied_slots(candidate) & target_slots:
            conflicts.append(candidate)
    return conflicts


def is_equippable(item: dict[str, Any]) -> bool:
    return infer_equipment_slot(item) is not None


def equipment_slot_label(slot: str | None) -> str:
    labels = {
        'main_hand': 'main hand',
        'off_hand': 'off hand',
        'two_hands': 'both hands',
        'body_armor': 'body armor',
    }
    return labels.get(slot or '', (slot or 'equipment').replace('_', ' '))
