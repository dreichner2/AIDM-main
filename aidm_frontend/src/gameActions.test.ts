import { describe, expect, it } from 'vitest'
import {
  abilityActionText,
  buildActionIntent,
  composerTextForMode,
  diceRollMessage,
  itemActionText,
  parseRollModifier,
  resolveRoll,
  stripComposerCommand,
  type AbilityOption,
  type ItemOption,
} from './gameActions'

const strength: AbilityOption = {
  key: 'strength',
  label: 'STR',
  score: '16',
  modifier: '+3',
}

const potion: ItemOption = {
  name: 'Healing Potion',
  quantity: '2',
}

describe('game action helpers', () => {
  it('rewrites composer prefixes without stacking old modes', () => {
    expect(composerTextForMode('ooc', 'I roll a d20: test', 'Ember', 'd20')).toBe('[OOC] test')
    expect(composerTextForMode('admin', '[OOC] force the door open', 'Ember', 'd20')).toBe(
      '[ADMIN] force the door open',
    )
    expect(composerTextForMode('ability', '[OOC] lift the gate', 'Ember', 'd20', strength)).toBe(
      'Ember attempts a STR check (+3): lift the gate',
    )
    expect(stripComposerCommand('/admin force the door open')).toBe('force the door open')
    expect(stripComposerCommand('/emote waves')).toBe('waves')
    expect(stripComposerCommand('Ember uses Healing Potion: test the sigil')).toBe('test the sigil')
  })

  it('builds ability and item text from selected character data', () => {
    expect(abilityActionText('Ember', strength, 'force the latch')).toBe(
      'Ember attempts a STR check (+3): force the latch',
    )
    expect(itemActionText('Ember', potion, 'before opening the door')).toBe(
      'Ember uses Healing Potion: before opening the door',
    )
  })

  it('calculates advantage rolls with modifier and hidden result metadata', () => {
    const rolls = [7, 18]
    const roll = resolveRoll(
      {
        die: 'd20',
        mode: 'advantage',
        modifier: parseRollModifier('+2'),
        reason: 'ward',
        resultVisibility: 'hidden_until_landed',
      },
      () => rolls.shift() ?? 1,
    )

    expect(roll.rolls).toEqual([7, 18])
    expect(roll.kept).toBe(18)
    expect(roll.total).toBe(20)
    expect(diceRollMessage(roll)).toBe('I roll a d20+2 for ward: 18 (advantage; rolls 7, 18) = 20')
  })

  it('builds typed action metadata for backend persistence', () => {
    const roll = resolveRoll(
      {
        die: 'd20',
        mode: 'normal',
        modifier: 1,
        reason: 'trap',
        resultVisibility: 'hidden_until_landed',
        targetPendingTurnId: 42,
      },
      () => 12,
    )

    const intent = buildActionIntent({
      mode: 'roll',
      message: diceRollMessage(roll),
      clientMessageId: 'local-test',
      source: 'dice_roller',
      roll,
    })

    expect(intent.kind).toBe('roll')
    expect(intent.client_message_id).toBe('local-test')
    expect(intent.roll).toMatchObject({
      die: 'd20',
      kept: 12,
      modifier: 1,
      total: 13,
      result_visibility: 'hidden_until_landed',
      target_pending_turn_id: 42,
    })
  })
})
