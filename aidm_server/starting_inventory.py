from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from aidm_server.canon_inventory import inventory_payload


STARTER_KITS: dict[str, list[dict[str, Any]]] = {
    'barbarian': [
        {'id': 'starter_barbarian_greataxe', 'name': 'Greataxe', 'quantity': 1, 'type': 'weapon', 'subtype': 'greataxe', 'equipped': True, 'slot': 'two_hands'},
        {'id': 'starter_barbarian_handaxe', 'name': 'Handaxe', 'quantity': 2, 'type': 'weapon', 'subtype': 'handaxe'},
        {'id': 'starter_barbarian_javelin', 'name': 'Javelin', 'quantity': 4, 'type': 'weapon', 'subtype': 'javelin'},
        {'id': 'starter_barbarian_pack', 'name': "Explorer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
        {'id': 'starter_barbarian_rations', 'name': 'Ration', 'quantity': 5, 'type': 'consumable'},
    ],
    'bard': [
        {'id': 'starter_bard_rapier', 'name': 'Rapier', 'quantity': 1, 'type': 'weapon', 'subtype': 'rapier', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_bard_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger'},
        {'id': 'starter_bard_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_bard_lute', 'name': 'Lute', 'quantity': 1, 'type': 'tool', 'weight': 2},
        {'id': 'starter_bard_pack', 'name': "Diplomat's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'cleric': [
        {'id': 'starter_cleric_mace', 'name': 'Mace', 'quantity': 1, 'type': 'weapon', 'subtype': 'mace', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_cleric_shield', 'name': 'Shield', 'quantity': 1, 'type': 'armor', 'subtype': 'shield', 'equipped': True, 'slot': 'off_hand'},
        {'id': 'starter_cleric_scale_mail', 'name': 'Scale Mail', 'quantity': 1, 'type': 'armor', 'subtype': 'medium armor', 'equipped': True, 'slot': 'body_armor', 'weight': 45},
        {'id': 'starter_cleric_holy_symbol', 'name': 'Holy Symbol', 'quantity': 1, 'type': 'focus', 'weight': 1},
        {'id': 'starter_cleric_pack', 'name': "Priest's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'druid': [
        {'id': 'starter_druid_scimitar', 'name': 'Scimitar', 'quantity': 1, 'type': 'weapon', 'subtype': 'scimitar', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_druid_wooden_shield', 'name': 'Wooden Shield', 'quantity': 1, 'type': 'armor', 'subtype': 'shield', 'equipped': True, 'slot': 'off_hand', 'weight': 6},
        {'id': 'starter_druid_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_druid_focus', 'name': 'Druidic Focus', 'quantity': 1, 'type': 'focus', 'weight': 1},
        {'id': 'starter_druid_pack', 'name': "Explorer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'fighter': [
        {'id': 'starter_fighter_longsword', 'name': 'Longsword', 'quantity': 1, 'type': 'weapon', 'subtype': 'longsword', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_fighter_shield', 'name': 'Shield', 'quantity': 1, 'type': 'armor', 'subtype': 'shield', 'equipped': True, 'slot': 'off_hand'},
        {'id': 'starter_fighter_chain_mail', 'name': 'Chain Mail', 'quantity': 1, 'type': 'armor', 'subtype': 'heavy armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_fighter_pack', 'name': "Explorer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
        {'id': 'starter_fighter_rations', 'name': 'Ration', 'quantity': 5, 'type': 'consumable'},
        {'id': 'starter_fighter_torches', 'name': 'Torch', 'quantity': 5, 'type': 'gear'},
    ],
    'monk': [
        {'id': 'starter_monk_quarterstaff', 'name': 'Quarterstaff', 'quantity': 1, 'type': 'weapon', 'subtype': 'quarterstaff', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_monk_darts', 'name': 'Dart', 'quantity': 10, 'type': 'weapon', 'subtype': 'dart', 'weight': 0.25},
        {'id': 'starter_monk_pack', 'name': "Explorer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
        {'id': 'starter_monk_rations', 'name': 'Ration', 'quantity': 5, 'type': 'consumable'},
    ],
    'paladin': [
        {'id': 'starter_paladin_longsword', 'name': 'Longsword', 'quantity': 1, 'type': 'weapon', 'subtype': 'longsword', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_paladin_shield', 'name': 'Shield', 'quantity': 1, 'type': 'armor', 'subtype': 'shield', 'equipped': True, 'slot': 'off_hand'},
        {'id': 'starter_paladin_chain_mail', 'name': 'Chain Mail', 'quantity': 1, 'type': 'armor', 'subtype': 'heavy armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_paladin_holy_symbol', 'name': 'Holy Symbol', 'quantity': 1, 'type': 'focus', 'weight': 1},
        {'id': 'starter_paladin_pack', 'name': "Priest's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'ranger': [
        {'id': 'starter_ranger_longbow', 'name': 'Longbow', 'quantity': 1, 'type': 'weapon', 'subtype': 'longbow', 'equipped': True, 'slot': 'two_hands', 'weight': 2},
        {'id': 'starter_ranger_shortsword', 'name': 'Shortsword', 'quantity': 1, 'type': 'weapon', 'subtype': 'shortsword'},
        {'id': 'starter_ranger_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_ranger_arrows', 'name': 'Arrow', 'quantity': 20, 'type': 'ammo', 'weight': 0.05},
        {'id': 'starter_ranger_pack', 'name': "Explorer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'rogue': [
        {'id': 'starter_rogue_rapier', 'name': 'Rapier', 'quantity': 1, 'type': 'weapon', 'subtype': 'rapier', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_rogue_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'off_hand'},
        {'id': 'starter_rogue_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_rogue_thieves_tools', 'name': "Thieves' Tools", 'quantity': 1, 'type': 'tool', 'weight': 1},
        {'id': 'starter_rogue_pack', 'name': "Burglar's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'sorcerer': [
        {'id': 'starter_sorcerer_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_sorcerer_crossbow', 'name': 'Light Crossbow', 'quantity': 1, 'type': 'weapon', 'subtype': 'crossbow', 'weight': 5},
        {'id': 'starter_sorcerer_focus', 'name': 'Arcane Focus', 'quantity': 1, 'type': 'focus', 'weight': 1},
        {'id': 'starter_sorcerer_pack', 'name': "Explorer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'warlock': [
        {'id': 'starter_warlock_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_warlock_crossbow', 'name': 'Light Crossbow', 'quantity': 1, 'type': 'weapon', 'subtype': 'crossbow', 'weight': 5},
        {'id': 'starter_warlock_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_warlock_focus', 'name': 'Arcane Focus', 'quantity': 1, 'type': 'focus', 'weight': 1},
        {'id': 'starter_warlock_pack', 'name': "Scholar's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'wizard': [
        {'id': 'starter_wizard_quarterstaff', 'name': 'Quarterstaff', 'quantity': 1, 'type': 'weapon', 'subtype': 'quarterstaff', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_wizard_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger'},
        {'id': 'starter_wizard_spellbook', 'name': 'Spellbook', 'quantity': 1, 'type': 'focus', 'weight': 3},
        {'id': 'starter_wizard_component_pouch', 'name': 'Component Pouch', 'quantity': 1, 'type': 'focus', 'weight': 2},
        {'id': 'starter_wizard_pack', 'name': "Scholar's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'gunslinger': [
        {'id': 'starter_gunslinger_pistol', 'name': 'Pistol', 'quantity': 1, 'type': 'weapon', 'subtype': 'firearm', 'equipped': True, 'slot': 'main_hand', 'weight': 3},
        {'id': 'starter_gunslinger_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger'},
        {'id': 'starter_gunslinger_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_gunslinger_ammunition', 'name': 'Ammunition', 'quantity': 20, 'type': 'ammo', 'weight': 0.05},
        {'id': 'starter_gunslinger_tools', 'name': "Gunsmith's Tools", 'quantity': 1, 'type': 'tool', 'weight': 5},
    ],
    'artificer': [
        {'id': 'starter_artificer_light_hammer', 'name': 'Light Hammer', 'quantity': 1, 'type': 'weapon', 'subtype': 'hammer', 'equipped': True, 'slot': 'main_hand', 'weight': 2},
        {'id': 'starter_artificer_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger'},
        {'id': 'starter_artificer_leather_armor', 'name': 'Leather Armor', 'quantity': 1, 'type': 'armor', 'subtype': 'light armor', 'equipped': True, 'slot': 'body_armor'},
        {'id': 'starter_artificer_tools', 'name': "Tinker's Tools", 'quantity': 1, 'type': 'tool', 'weight': 10},
        {'id': 'starter_artificer_pack', 'name': "Artisan's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'scholar': [
        {'id': 'starter_scholar_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_scholar_notebook', 'name': 'Notebook', 'quantity': 1, 'type': 'gear', 'weight': 1},
        {'id': 'starter_scholar_ink_pen', 'name': 'Ink and Pen', 'quantity': 1, 'type': 'gear', 'weight': 0.1},
        {'id': 'starter_scholar_pack', 'name': "Scholar's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'noble': [
        {'id': 'starter_noble_rapier', 'name': 'Rapier', 'quantity': 1, 'type': 'weapon', 'subtype': 'rapier', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_noble_fine_clothes', 'name': 'Fine Clothes', 'quantity': 1, 'type': 'clothing', 'equipped': True, 'slot': 'clothing', 'weight': 6},
        {'id': 'starter_noble_signet_ring', 'name': 'Signet Ring', 'quantity': 1, 'type': 'gear', 'weight': 0.1},
        {'id': 'starter_noble_pack', 'name': "Diplomat's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'medic': [
        {'id': 'starter_medic_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_medic_kit', 'name': "Healer's Kit", 'quantity': 1, 'type': 'tool', 'weight': 3},
        {'id': 'starter_medic_bag', 'name': 'Medical Bag', 'quantity': 1, 'type': 'gear', 'weight': 5},
        {'id': 'starter_medic_clothes', 'name': "Traveler's Clothes", 'quantity': 1, 'type': 'clothing', 'equipped': True, 'slot': 'clothing', 'weight': 4},
    ],
    'operative': [
        {'id': 'starter_operative_sidearm', 'name': 'Sidearm', 'quantity': 1, 'type': 'weapon', 'subtype': 'firearm', 'equipped': True, 'slot': 'main_hand', 'weight': 3},
        {'id': 'starter_operative_knife', 'name': 'Knife', 'quantity': 1, 'type': 'weapon', 'subtype': 'knife'},
        {'id': 'starter_operative_vest', 'name': 'Tactical Vest', 'quantity': 1, 'type': 'armor', 'subtype': 'vest', 'equipped': True, 'slot': 'body_armor', 'weight': 8},
        {'id': 'starter_operative_ammunition', 'name': 'Ammunition', 'quantity': 20, 'type': 'ammo', 'weight': 0.05},
        {'id': 'starter_operative_field_pack', 'name': 'Field Pack', 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'entertainer': [
        {'id': 'starter_entertainer_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_entertainer_instrument', 'name': 'Musical Instrument', 'quantity': 1, 'type': 'tool', 'weight': 2},
        {'id': 'starter_entertainer_costume', 'name': 'Costume', 'quantity': 1, 'type': 'clothing', 'equipped': True, 'slot': 'clothing', 'weight': 4},
        {'id': 'starter_entertainer_pack', 'name': "Performer's Pack", 'quantity': 1, 'type': 'gear', 'weight': 5},
    ],
    'professional': [
        {'id': 'starter_professional_dagger', 'name': 'Dagger', 'quantity': 1, 'type': 'weapon', 'subtype': 'dagger', 'equipped': True, 'slot': 'main_hand'},
        {'id': 'starter_professional_clothes', 'name': 'Professional Clothes', 'quantity': 1, 'type': 'clothing', 'equipped': True, 'slot': 'clothing', 'weight': 4},
        {'id': 'starter_professional_notebook', 'name': 'Notebook', 'quantity': 1, 'type': 'gear', 'weight': 1},
        {'id': 'starter_professional_tools', 'name': 'Work Tools', 'quantity': 1, 'type': 'tool', 'weight': 5},
    ],
}

KEYWORD_KITS: tuple[tuple[tuple[str, ...], str], ...] = (
    (('archer', 'sniper', 'bow'), 'ranger'),
    (('gunslinger', 'firearm', 'pistol', 'rifle'), 'gunslinger'),
    (('alchemist', 'artificer', 'engineer', 'inventor', 'smith', 'technomancer'), 'artificer'),
    (('healer', 'oracle', 'priest', 'shaman', 'warpriest', 'inquisitor'), 'cleric'),
    (('mage', 'witch', 'arcanist', 'psion', 'magus', 'summoner', 'elementalist', 'psychic', 'medium', 'occultist', 'mesmerist', 'necromancer', 'mystic', 'dragon'), 'wizard'),
    (('knight', 'warden', 'guardian', 'soldier', 'warrior', 'cavalier'), 'fighter'),
    (('beastmaster', 'shapeshifter'), 'druid'),
    (('assassin', 'scout', 'thief', 'ninja', 'swashbuckler', 'shadowblade', 'investigator', 'blood hunter'), 'rogue'),
    (('scholar', 'educator'), 'scholar'),
    (('noble', 'merchant', 'marshal'), 'noble'),
    (('medic', 'medical'), 'medic'),
    (('operative', 'pilot', 'public safety', 'street operator'), 'operative'),
    (('business', 'legal', 'media', 'service worker', 'tradesperson', 'professional'), 'professional'),
    (('entertainer', 'skald'), 'entertainer'),
)


def _normalize_class_text(class_name: str | None) -> str:
    base = str(class_name or '').split('-', 1)[0]
    return re.sub(r'[^a-z0-9]+', ' ', base.lower()).strip()


def _starter_kit_key(class_name: str | None) -> str | None:
    normalized = _normalize_class_text(class_name)
    if not normalized:
        return None
    compact = normalized.replace(' ', '_')
    if compact in STARTER_KITS:
        return compact
    tokens = set(normalized.split())
    for keywords, kit_key in KEYWORD_KITS:
        if any(keyword in tokens or keyword in normalized for keyword in keywords):
            return kit_key
    return None


def starting_inventory_for_class(class_name: str | None) -> list[dict[str, Any]]:
    kit_key = _starter_kit_key(class_name)
    if not kit_key:
        return []
    return inventory_payload(deepcopy(STARTER_KITS[kit_key]))
