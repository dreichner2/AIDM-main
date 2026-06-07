export type ComposerMode = 'action' | 'roll' | 'ability' | 'item' | 'interact' | 'emote' | 'ooc' | 'admin'
export type RollMode = 'normal' | 'advantage' | 'disadvantage'
export type ResultVisibility = 'hidden_until_landed' | 'visible'
export type InteractionType = 'speak_to' | 'act_on' | 'give_to' | 'take_from'

export const DICE_OPTIONS = ['d4', 'd6', 'd8', 'd10', 'd12', 'd20', 'd100'] as const
export const INTERACTION_TYPE_OPTIONS: Array<{ value: InteractionType; label: string }> = [
  { value: 'speak_to', label: 'Speak to' },
  { value: 'act_on', label: 'Act on' },
  { value: 'give_to', label: 'Give to' },
  { value: 'take_from', label: 'Take from' },
]

export type AbilityOption = {
  key: string
  label: string
  score: string
  modifier: string
}

export type ItemOption = {
  name: string
  quantity: string
}

export type InteractionTarget = {
  player_id: number
  character_name: string
  player_name: string
  active: boolean
}

export type RollDraft = {
  die: string
  modifier: number
  mode: RollMode
  reason: string
  resultVisibility: ResultVisibility
  targetPendingTurnId?: number | null
}

export type RollResult = RollDraft & {
  rolls: number[]
  kept: number
  total: number
}

export type ActionIntent = {
  kind: ComposerMode | 'message'
  source: 'composer' | 'dice_roller'
  text: string
  client_message_id: string
  roll?: {
    die: string
    mode: RollMode
    modifier: number
    rolls: number[]
    kept: number
    total: number
    result_visibility: ResultVisibility
    reason: string
    target_pending_turn_id?: number
  }
  ability?: {
    key: string
    label: string
    modifier: number
  }
  item?: {
    name: string
    quantity: number
  }
  interaction?: {
    type: InteractionType
    label: string
  }
  target?: {
    player_id: number
    character_name: string
    player_name: string
  }
}

const COMPOSER_PREFIX_PATTERNS = [
  /^\[OOC\]\s*/i,
  /^\[ADMIN\]\s*/i,
  /^\/ooc\s+/i,
  /^\/admin\s+/i,
  /^\/emote\s+/i,
  /^I roll a d\d{1,3}(?:\s*[+-]\s*\d+)?(?:\s*\([^)]*\))?\s*:\s*/i,
  /^[^:\n]{1,80}\s+attempts an ability check(?:\s*\([^)]*\))?:\s*/i,
  /^[^:\n]{1,80}\s+attempts a [^:\n]{1,40} check(?:\s*\([^)]*\))?:\s*/i,
  /^[^:\n]{1,80}\s+uses\s+[^:\n]{1,80}:\s*/i,
  /^[^:\n]{1,80}\s+uses\s+/i,
  /^[^:\n]{1,80}\s+says to\s+[^:\n]{1,80}:\s*/i,
  /^[^:\n]{1,80}\s+directs an action at\s+[^:\n]{1,80}:\s*/i,
  /^[^:\n]{1,80}\s+gives something to\s+[^:\n]{1,80}:\s*/i,
  /^[^:\n]{1,80}\s+tries to take something from\s+[^:\n]{1,80}:\s*/i,
]

export function stripComposerCommand(value: string) {
  let next = value.trimStart()
  COMPOSER_PREFIX_PATTERNS.forEach((pattern) => {
    next = next.replace(pattern, '')
  })
  return next
}

export function composerModeLabel(mode: ComposerMode, die: string) {
  if (mode === 'admin') return 'Admin Override'
  if (mode === 'ooc') return 'Out of Character'
  if (mode === 'roll') return `Roll ${die.toUpperCase()}`
  if (mode === 'ability') return 'Ability Check'
  if (mode === 'item') return 'Item Use'
  if (mode === 'interact') return 'Player Interaction'
  if (mode === 'emote') return 'Emote'
  return 'In Character'
}

export function interactionTypeLabel(type: InteractionType) {
  return INTERACTION_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? 'Interact with'
}

export function normalizeDie(die: string) {
  const normalized = die.trim().toLowerCase()
  return DICE_OPTIONS.includes(normalized as (typeof DICE_OPTIONS)[number]) ? normalized : 'd20'
}

export function dieSides(die: string) {
  const parsed = Number(normalizeDie(die).replace(/^d/i, ''))
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 20
}

export function formatModifier(value: number) {
  if (!Number.isFinite(value) || value === 0) return ''
  return value > 0 ? `+${value}` : String(value)
}

export function parseRollModifier(value: string) {
  const parsed = Number(value.replace(/\s+/g, ''))
  if (!Number.isFinite(parsed)) return 0
  return Math.max(-99, Math.min(99, Math.trunc(parsed)))
}

export function createClientMessageId() {
  const cryptoSource = globalThis.crypto
  if (typeof cryptoSource?.randomUUID === 'function') {
    return cryptoSource.randomUUID()
  }
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function rollDie(die: string) {
  const sides = dieSides(die)
  const cryptoSource = globalThis.crypto
  if (typeof cryptoSource?.getRandomValues === 'function') {
    const value = new Uint32Array(1)
    cryptoSource.getRandomValues(value)
    return (value[0] % sides) + 1
  }
  return Math.floor(Math.random() * sides) + 1
}

export function resolveRoll(draft: RollDraft, roller: (die: string) => number = rollDie): RollResult {
  const die = normalizeDie(draft.die)
  const first = roller(die)
  const rolls = draft.mode === 'normal' ? [first] : [first, roller(die)]
  const kept =
    draft.mode === 'advantage'
      ? Math.max(...rolls)
      : draft.mode === 'disadvantage'
        ? Math.min(...rolls)
        : rolls[0]
  const modifier = Math.max(-99, Math.min(99, Math.trunc(draft.modifier || 0)))
  return {
    die,
    modifier,
    mode: draft.mode,
    reason: draft.reason.trim().slice(0, 240),
    resultVisibility: draft.resultVisibility,
    targetPendingTurnId:
      typeof draft.targetPendingTurnId === 'number' && Number.isInteger(draft.targetPendingTurnId) && draft.targetPendingTurnId > 0
        ? draft.targetPendingTurnId
        : null,
    rolls,
    kept,
    total: kept + modifier,
  }
}

export function diceRollMessage(roll: RollResult) {
  const modifier = formatModifier(roll.modifier)
  const rollSummary =
    roll.mode === 'normal'
      ? `${roll.kept}`
      : `${roll.kept} (${roll.mode}; rolls ${roll.rolls.join(', ')})`
  const reason = roll.reason ? ` for ${roll.reason}` : ''
  return `I roll a ${roll.die}${modifier}${reason}: ${rollSummary}${roll.modifier ? ` = ${roll.total}` : ''}`
}

export function abilityActionText(characterName: string, ability: AbilityOption | null, current: string) {
  const body = stripComposerCommand(current)
  const label = ability?.label ?? 'ability'
  const modifier = ability?.modifier && ability.modifier !== '—' ? ` (${ability.modifier})` : ''
  return `${characterName} attempts a ${label} check${modifier}: ${body}`.trim()
}

export function itemActionText(characterName: string, item: ItemOption | null, current: string) {
  const body = stripComposerCommand(current)
  const itemName = item?.name ?? 'item'
  return `${characterName} uses ${itemName}${body ? `: ${body}` : ''}`.trim()
}

export function interactionActionText(
  characterName: string,
  target: InteractionTarget | null,
  interactionType: InteractionType,
  current: string,
) {
  const body = stripComposerCommand(current)
  const targetName = target?.character_name || 'another player'
  if (interactionType === 'speak_to') {
    return `${characterName} says to ${targetName}: ${body}`.trim()
  }
  if (interactionType === 'give_to') {
    return `${characterName} gives something to ${targetName}: ${body}`.trim()
  }
  if (interactionType === 'take_from') {
    return `${characterName} tries to take something from ${targetName}: ${body}`.trim()
  }
  return `${characterName} directs an action at ${targetName}: ${body}`.trim()
}

export function composerTextForMode(
  mode: ComposerMode,
  current: string,
  characterName: string,
  die: string,
  ability: AbilityOption | null = null,
  item: ItemOption | null = null,
  interactionTarget: InteractionTarget | null = null,
  interactionType: InteractionType = 'speak_to',
) {
  const body = stripComposerCommand(current)
  if (mode === 'roll') return `I roll a ${normalizeDie(die)}: ${body}`
  if (mode === 'admin') return `[ADMIN] ${body}`
  if (mode === 'ooc') return `[OOC] ${body}`
  if (mode === 'ability') return abilityActionText(characterName, ability, current)
  if (mode === 'item') return itemActionText(characterName, item, current)
  if (mode === 'interact') {
    return interactionActionText(characterName, interactionTarget, interactionType, current)
  }
  if (mode === 'emote') return `/emote ${body}`
  return body
}

export function buildActionIntent({
  mode,
  message,
  clientMessageId,
  source = 'composer',
  roll,
  ability,
  item,
  interactionType,
  interactionTarget,
}: {
  mode: ComposerMode
  message: string
  clientMessageId: string
  source?: ActionIntent['source']
  roll?: RollResult | null
  ability?: AbilityOption | null
  item?: ItemOption | null
  interactionType?: InteractionType
  interactionTarget?: InteractionTarget | null
}): ActionIntent {
  const kind = mode === 'action' ? 'message' : mode
  const intent: ActionIntent = {
    kind,
    source,
    text: message,
    client_message_id: clientMessageId,
  }
  if (mode === 'roll' && roll) {
    intent.roll = {
      die: roll.die,
      mode: roll.mode,
      modifier: roll.modifier,
      rolls: roll.rolls,
      kept: roll.kept,
      total: roll.total,
      result_visibility: roll.resultVisibility,
      reason: roll.reason,
    }
    if (roll.targetPendingTurnId) {
      intent.roll.target_pending_turn_id = roll.targetPendingTurnId
    }
  }
  if (mode === 'ability' && ability) {
    intent.ability = {
      key: ability.key,
      label: ability.label,
      modifier: Number(ability.modifier.replace(/[^0-9-]/g, '')) || 0,
    }
  }
  if (mode === 'item' && item) {
    intent.item = {
      name: item.name,
      quantity: Number(item.quantity.replace(/[^0-9-]/g, '')) || 1,
    }
  }
  if (mode === 'interact' && interactionTarget) {
    const normalizedInteractionType = interactionType ?? 'speak_to'
    intent.interaction = {
      type: normalizedInteractionType,
      label: interactionTypeLabel(normalizedInteractionType),
    }
    intent.target = {
      player_id: interactionTarget.player_id,
      character_name: interactionTarget.character_name,
      player_name: interactionTarget.player_name,
    }
  }
  return intent
}
