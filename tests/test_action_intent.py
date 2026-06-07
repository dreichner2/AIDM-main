from __future__ import annotations

from aidm_server.action_intent import apply_action_intent_to_rule_hint, validate_action_intent
from aidm_server.rules import RuleHint


def test_validate_roll_action_intent_normalizes_roll_metadata():
    intent, error = validate_action_intent(
        {
            'kind': 'roll',
            'source': 'dice_roller',
            'text': 'I roll a d20+2: 18 = 20',
            'client_message_id': 'local-test-1',
            'roll': {
                'die': 'D20',
                'mode': 'advantage',
                'modifier': 2,
                'rolls': [9, 18],
                'kept': 18,
                'total': 20,
                'result_visibility': 'hidden_until_landed',
                'reason': 'checking the lock',
                'target_pending_turn_id': '42',
            },
        }
    )

    assert error is None
    assert intent is not None
    assert intent['kind'] == 'roll'
    assert intent['client_message_id'] == 'local-test-1'
    assert intent['roll']['die'] == 'd20'
    assert intent['roll']['total'] == 20
    assert intent['roll']['target_pending_turn_id'] == 42


def test_validate_roll_action_rejects_inconsistent_total():
    intent, error = validate_action_intent(
        {
            'kind': 'roll',
            'roll': {
                'die': 'd20',
                'mode': 'normal',
                'modifier': 2,
                'rolls': [12],
                'kept': 12,
                'total': 99,
            },
        }
    )

    assert intent is None
    assert error == 'roll.total must equal roll.kept plus roll.modifier.'


def test_validate_roll_action_rejects_invalid_pending_target():
    intent, error = validate_action_intent(
        {
            'kind': 'roll',
            'roll': {
                'die': 'd20',
                'mode': 'normal',
                'rolls': [12],
                'kept': 12,
                'total': 12,
                'target_pending_turn_id': 0,
            },
        }
    )

    assert intent is None
    assert error == 'roll.target_pending_turn_id must be a positive integer.'


def test_apply_roll_intent_overrides_natural_language_rule_hint():
    hint = RuleHint(
        requires_roll=False,
        roll_type=None,
        dc_hint=None,
        reason='Narrative action',
        confidence=0.1,
    )
    intent, error = validate_action_intent(
        {
            'kind': 'roll',
            'roll': {
                'die': 'd20',
                'mode': 'normal',
                'modifier': 3,
                'rolls': [17],
                'kept': 17,
                'total': 20,
                'reason': 'saving throw',
            },
        }
    )

    assert error is None
    updated = apply_action_intent_to_rule_hint(intent, hint)

    assert updated.requires_roll is True
    assert updated.roll_type == 'check'
    assert updated.roll_value == 20
    assert updated.outcome_deferred is False
    assert updated.confidence == 0.99


def test_validate_ability_and_item_intents():
    ability, ability_error = validate_action_intent(
        {
            'kind': 'ability',
            'ability': {'key': 'strength', 'label': 'STR', 'modifier': 4},
        }
    )
    item, item_error = validate_action_intent(
        {
            'kind': 'item',
            'item': {'name': 'Healing Potion', 'quantity': 2},
        }
    )

    assert ability_error is None
    assert item_error is None
    assert ability['ability']['key'] == 'strength'
    assert item['item']['name'] == 'Healing Potion'


def test_validate_interaction_intent_normalizes_target_metadata():
    intent, error = validate_action_intent(
        {
            'kind': 'interact',
            'source': 'composer',
            'text': 'Seraphina says to Borin: hold the bridge',
            'client_message_id': 'interact-1',
            'interaction': {'type': 'speak_to', 'label': 'Speak to'},
            'target': {
                'player_id': '42',
                'character_name': 'Borin',
                'player_name': 'Maya',
            },
        }
    )

    assert error is None
    assert intent is not None
    assert intent['kind'] == 'interact'
    assert intent['interaction'] == {'type': 'speak_to', 'label': 'Speak to'}
    assert intent['target'] == {
        'player_id': 42,
        'character_name': 'Borin',
        'player_name': 'Maya',
    }


def test_validate_admin_action_intent_normalizes_without_passcode():
    intent, error = validate_action_intent(
        {
            'kind': 'admin',
            'source': 'composer',
            'text': '[ADMIN] make the door open',
            'client_message_id': 'admin-1',
            'admin_passcode': 'must-not-be-persisted',
        }
    )

    assert error is None
    assert intent == {
        'kind': 'admin',
        'text': '[ADMIN] make the door open',
        'source': 'composer',
        'client_message_id': 'admin-1',
    }
