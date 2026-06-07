import { useEffect, useMemo, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { Socket } from 'socket.io-client'
import {
  buildActionIntent,
  composerTextForMode,
  createClientMessageId,
  diceRollMessage,
  normalizeDie,
  parseRollModifier,
  resolveRoll,
  stripComposerCommand,
  type AbilityOption,
  type ActionIntent,
  type ComposerMode,
  type InteractionTarget,
  type InteractionType,
  type ItemOption,
  type RollMode,
  type RollResult,
} from './gameActions'
import type { PendingRollOption } from './gameSelectors'
import type { ActivePlayer, Campaign, Player, StreamingTurn, TimelineEntry } from './types'

type DiceRollState = {
  die: string
  result: number
  message: string
  actionIntent: ActionIntent
  roll: RollResult
  targetLabel: string | null
  rollKey: number
  status: 'rolling' | 'sending'
}

type UseComposerActionsOptions = {
  activePlayers: ActivePlayer[]
  abilityOptions: AbilityOption[]
  campaign: Campaign | null
  itemOptions: ItemOption[]
  pendingRollOptions: PendingRollOption[]
  players: Player[]
  selectedCampaignId: number | null
  selectedPlayer: Player | null
  selectedPlayerId: number | null
  selectedSessionId: number | null
  sendPending: boolean
  setOptimisticEntries: Dispatch<SetStateAction<TimelineEntry[]>>
  setSendPending: Dispatch<SetStateAction<boolean>>
  socketRef: RefObject<Socket | null>
  stopTtsAudio: () => void
  streamingTurn: StreamingTurn | null
  pushError: (category: 'validation', message: string) => void
}

export function useComposerActions({
  activePlayers,
  abilityOptions,
  campaign,
  itemOptions,
  pendingRollOptions,
  players,
  selectedCampaignId,
  selectedPlayer,
  selectedPlayerId,
  selectedSessionId,
  sendPending,
  setOptimisticEntries,
  setSendPending,
  socketRef,
  stopTtsAudio,
  streamingTurn,
  pushError,
}: UseComposerActionsOptions) {
  const [actionText, setActionText] = useState('')
  const [composerMode, setComposerMode] = useState<ComposerMode>('action')
  const [selectedDie, setSelectedDie] = useState('d20')
  const [rollModifier, setRollModifier] = useState('0')
  const [rollMode, setRollMode] = useState<RollMode>('normal')
  const [rollReason, setRollReason] = useState('')
  const [rawRollTargetPendingTurnId, setRollTargetPendingTurnId] = useState('')
  const [selectedAbilityKey, setSelectedAbilityKey] = useState('strength')
  const [selectedItemName, setSelectedItemName] = useState('')
  const [selectedInteractionType, setSelectedInteractionType] = useState<InteractionType>('speak_to')
  const [rawSelectedInteractionTargetId, setSelectedInteractionTargetId] = useState('')
  const [adminPasscode, setAdminPasscode] = useState(() => sessionStorage.getItem('aidm:adminPasscode') ?? '')
  const [adminToolsUnlocked, setAdminToolsUnlocked] = useState(false)
  const [diceRoll, setDiceRoll] = useState<DiceRollState | null>(null)
  const diceRollKeyRef = useRef(0)

  useEffect(() => {
    const trimmed = adminPasscode.trim()
    if (trimmed) {
      sessionStorage.setItem('aidm:adminPasscode', trimmed)
    } else {
      sessionStorage.removeItem('aidm:adminPasscode')
    }
  }, [adminPasscode])

  const selectedAbility =
    abilityOptions.find((ability) => ability.key === selectedAbilityKey) ?? abilityOptions[0] ?? null
  const selectedItem =
    itemOptions.find((item) => item.name === selectedItemName) ?? itemOptions[0] ?? null
  const activePlayerIds = useMemo(
    () => new Set(activePlayers.map((player) => player.id)),
    [activePlayers],
  )
  const interactionTargets = useMemo<InteractionTarget[]>(
    () =>
      players
        .filter((player) => player.player_id !== selectedPlayerId)
        .map((player) => ({
          player_id: player.player_id,
          character_name: player.character_name || player.name || `Player ${player.player_id}`,
          player_name: player.name || 'Campaign player',
          active: activePlayerIds.has(player.player_id),
        })),
    [activePlayerIds, players, selectedPlayerId],
  )
  const selectedInteractionTargetId =
    rawSelectedInteractionTargetId &&
    interactionTargets.some((target) => String(target.player_id) === rawSelectedInteractionTargetId)
      ? rawSelectedInteractionTargetId
      : interactionTargets[0]?.player_id
        ? String(interactionTargets[0].player_id)
        : ''
  const selectedInteractionTarget =
    interactionTargets.find((target) => String(target.player_id) === selectedInteractionTargetId) ?? null
  const rollTargetPendingTurnId =
    rawRollTargetPendingTurnId &&
    pendingRollOptions.some((option) => String(option.turnId) === rawRollTargetPendingTurnId)
      ? rawRollTargetPendingTurnId
      : ''

  const toggleAdminTools = () => {
    if (adminToolsUnlocked) {
      setAdminToolsUnlocked(false)
      setComposerMode((current) => (current === 'admin' ? 'action' : current))
      setActionText((current) => stripComposerCommand(current))
      return
    }
    setAdminToolsUnlocked(true)
  }

  const submitAction = (overrideMessage?: string, overrideIntent?: ActionIntent) => {
    if (sendPending || streamingTurn) {
      pushError('validation', 'Wait for the current DM response to save before sending again.')
      return
    }
    if (
      !socketRef.current ||
      !selectedSessionId ||
      !selectedCampaignId ||
      !campaign ||
      !selectedPlayerId
    ) {
      pushError('validation', 'Choose a campaign, session, and player before sending.')
      return
    }
    const message = (overrideMessage ?? actionText).trim()
    if (!message) return
    const trimmedAdminPasscode = adminPasscode.trim()
    if (!overrideIntent && composerMode === 'admin' && !trimmedAdminPasscode) {
      pushError('validation', 'Admin passcode is required for Admin mode.')
      return
    }
    if (!overrideIntent && composerMode === 'interact' && !selectedInteractionTarget) {
      pushError('validation', 'Choose another player before sending an interaction.')
      return
    }
    const clientMessageId = overrideIntent?.client_message_id ?? createClientMessageId()
    const actionIntent =
      overrideIntent ??
      buildActionIntent({
        mode: composerMode,
        message,
        clientMessageId,
        ability: selectedAbility,
        item: selectedItem,
        interactionType: selectedInteractionType,
        interactionTarget: selectedInteractionTarget,
      })

    stopTtsAudio()
    setSendPending(true)
    setOptimisticEntries((current) => [
      ...current,
      {
        id: `local-${Date.now()}`,
        role: 'player',
        speaker: selectedPlayer?.character_name ?? 'Player',
        text: message,
        timestamp: new Date().toISOString(),
        metadata: {
          client_message_id: clientMessageId,
          action_intent: actionIntent,
          persistence_status: 'pending',
        },
      },
    ])
    socketRef.current.emit('send_message', {
      session_id: selectedSessionId,
      campaign_id: selectedCampaignId,
      world_id: campaign.world_id,
      player_id: selectedPlayerId,
      message,
      client_message_id: clientMessageId,
      action_intent: actionIntent,
      ...(actionIntent.kind === 'admin' ? { admin_passcode: trimmedAdminPasscode } : {}),
    })
    setActionText('')
  }

  const applyComposerMode = (mode: ComposerMode, die = selectedDie) => {
    if (mode === 'admin' && !adminToolsUnlocked) return
    setComposerMode(mode)
    setActionText((current) =>
      composerTextForMode(
        mode,
        current,
        selectedPlayer?.character_name ?? 'I',
        die,
        selectedAbility,
        selectedItem,
        selectedInteractionTarget,
        selectedInteractionType,
      ),
    )
  }

  const updateSelectedDie = (die: string) => {
    const normalizedDie = normalizeDie(die)
    setSelectedDie(normalizedDie)
    if (composerMode === 'roll') {
      setActionText((current) =>
        composerTextForMode('roll', current, selectedPlayer?.character_name ?? 'I', normalizedDie, selectedAbility, selectedItem),
      )
    }
  }

  const startDiceRoll = (die = selectedDie) => {
    if (sendPending) {
      pushError('validation', 'Wait for the current DM response before rolling again.')
      return
    }
    if (
      !socketRef.current ||
      !selectedSessionId ||
      !selectedCampaignId ||
      !campaign ||
      !selectedPlayerId
    ) {
      pushError('validation', 'Choose a campaign, session, and player before rolling.')
      return
    }

    const normalizedDie = normalizeDie(die)
    const targetPendingTurnId = rollTargetPendingTurnId ? Number(rollTargetPendingTurnId) : null
    const targetOption = pendingRollOptions.find((option) => option.turnId === targetPendingTurnId) ?? null
    const roll = resolveRoll({
      die: normalizedDie,
      modifier: parseRollModifier(rollModifier),
      mode: rollMode,
      reason: rollReason,
      resultVisibility: 'hidden_until_landed',
      targetPendingTurnId,
    })
    const message = diceRollMessage(roll)
    const clientMessageId = createClientMessageId()
    const actionIntent = buildActionIntent({
      mode: 'roll',
      message,
      clientMessageId,
      source: 'dice_roller',
      roll,
    })
    setSelectedDie(normalizedDie)
    setComposerMode('roll')
    setActionText(message)
    setDiceRoll({
      die: normalizedDie,
      result: roll.kept,
      message,
      actionIntent,
      roll,
      targetLabel: targetOption ? `${targetOption.label} - ${targetOption.detail}` : null,
      rollKey: (diceRollKeyRef.current += 1),
      status: 'rolling',
    })
  }

  const completeDiceRoll = () => {
    if (!diceRoll || diceRoll.status !== 'rolling') return
    const { rollKey, message, actionIntent } = diceRoll
    setDiceRoll((current) =>
      current?.rollKey === rollKey ? { ...current, status: 'sending' } : current,
    )
    submitAction(message, actionIntent)
    window.setTimeout(() => {
      setDiceRoll((current) => (current?.rollKey === rollKey ? null : current))
    }, 450)
  }

  const closeDiceRoll = () => {
    setDiceRoll(null)
  }

  return {
    actionText,
    adminPasscode,
    adminToolsUnlocked,
    applyComposerMode,
    closeDiceRoll,
    completeDiceRoll,
    composerMode,
    diceRoll,
    interactionTargets,
    rollMode,
    rollModifier,
    rollReason,
    rollTargetPendingTurnId,
    selectedAbility,
    selectedDie,
    selectedInteractionTarget,
    selectedInteractionTargetId,
    selectedInteractionType,
    selectedItem,
    setActionText,
    setAdminPasscode,
    setSelectedInteractionTargetId,
    setSelectedInteractionType,
    setRollMode,
    setRollModifier,
    setRollReason,
    setRollTargetPendingTurnId,
    setSelectedAbilityKey,
    setSelectedItemName,
    startDiceRoll,
    submitAction,
    toggleAdminTools,
    updateSelectedDie,
  }
}
