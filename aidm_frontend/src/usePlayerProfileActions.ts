import { useCallback, useState, type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { apiFetch } from './api'
import type { Player, PlayerDetail } from './types'

type ValueUpdater<T> = T | ((current: T) => T)

export type PlayerEditDialogState = {
  mode: 'create' | 'edit'
  campaignId: number | null
  player: Player | null
  name: string
  characterName: string
  race: string
  charClass: string
  level: string
  error: string
  pending: boolean
} | null

export type PlayerDeleteDialogState = {
  player: Player
  error: string
  pending: boolean
} | null

type UsePlayerProfileActionsOptions = {
  auth: string
  baseUrl: string
  selectedPlayer: Player | null
  selectedCampaignId: number | null
  rememberDialogTrigger: () => void
  refreshCampaignWorkspace: (campaignId: number) => Promise<void>
  setProfileSettingsOpen: Dispatch<SetStateAction<boolean>>
  setPlayerDetail: (value: ValueUpdater<PlayerDetail | null>) => void
  setSelectedPlayerId: (value: ValueUpdater<number | null>) => void
  playerUpserted: (player: Player) => void
  pushError: (category: 'persistence', message: string) => void
}

function playerDialogStateFromPlayer(player: Player): NonNullable<PlayerEditDialogState> {
  return {
    mode: 'edit',
    campaignId: player.campaign_id,
    player,
    name: player.name ?? '',
    characterName: player.character_name ?? '',
    race: player.race ?? '',
    charClass: player.char_class || player.class_ || '',
    level: String(player.level ?? 1),
    error: '',
    pending: false,
  }
}

export function usePlayerProfileActions({
  auth,
  baseUrl,
  selectedPlayer,
  selectedCampaignId,
  rememberDialogTrigger,
  refreshCampaignWorkspace,
  setProfileSettingsOpen,
  setPlayerDetail,
  setSelectedPlayerId,
  playerUpserted,
  pushError,
}: UsePlayerProfileActionsOptions) {
  const [playerEditDialog, setPlayerEditDialog] = useState<PlayerEditDialogState>(null)
  const [playerDeleteDialog, setPlayerDeleteDialog] = useState<PlayerDeleteDialogState>(null)

  const openPlayerEditDialog = useCallback(() => {
    if (!selectedPlayer) return
    rememberDialogTrigger()
    setProfileSettingsOpen(false)
    setPlayerEditDialog(playerDialogStateFromPlayer(selectedPlayer))
  }, [rememberDialogTrigger, selectedPlayer, setProfileSettingsOpen])

  const openCreatePlayerDialog = useCallback((campaignId: number | null) => {
    if (!campaignId) return
    rememberDialogTrigger()
    setProfileSettingsOpen(false)
    setPlayerEditDialog({
      mode: 'create',
      campaignId,
      player: null,
      name: '',
      characterName: '',
      race: '',
      charClass: '',
      level: '1',
      error: '',
      pending: false,
    })
  }, [rememberDialogTrigger, setProfileSettingsOpen])

  const closePlayerEditDialog = useCallback(() => {
    if (playerEditDialog?.pending) return
    setPlayerEditDialog(null)
  }, [playerEditDialog?.pending])

  const openPlayerDeleteDialog = useCallback(() => {
    if (!selectedPlayer) return
    rememberDialogTrigger()
    setProfileSettingsOpen(false)
    setPlayerDeleteDialog({
      player: selectedPlayer,
      error: '',
      pending: false,
    })
  }, [rememberDialogTrigger, selectedPlayer, setProfileSettingsOpen])

  const closePlayerDeleteDialog = useCallback(() => {
    if (playerDeleteDialog?.pending) return
    setPlayerDeleteDialog(null)
  }, [playerDeleteDialog?.pending])

  const submitPlayerEditDialog = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!playerEditDialog) return
    const name = playerEditDialog.name.trim()
    const characterName = playerEditDialog.characterName.trim()
    const level = Number(playerEditDialog.level)
    if (!name || !characterName) {
      setPlayerEditDialog((current) =>
        current ? { ...current, error: 'Player and character names are required.' } : current,
      )
      return
    }
    if (!Number.isInteger(level) || level < 1 || level > 20) {
      setPlayerEditDialog((current) =>
        current ? { ...current, error: 'Level must be 1 through 20.' } : current,
      )
      return
    }

    const dialogMode = playerEditDialog.mode
    const campaignId = playerEditDialog.campaignId
    const playerId = playerEditDialog.player?.player_id ?? null
    setPlayerEditDialog((current) => (current ? { ...current, pending: true, error: '' } : current))
    try {
      let updated: PlayerDetail
      const body = JSON.stringify({
        name,
        character_name: characterName,
        race: playerEditDialog.race.trim(),
        char_class: playerEditDialog.charClass.trim(),
        level,
      })
      if (dialogMode === 'create') {
        if (!campaignId) throw new Error('Choose a campaign before creating a character.')
        const created = await apiFetch<{ player_id: number }>(
          baseUrl,
          `/api/players/campaigns/${campaignId}/players`,
          auth,
          {
            method: 'POST',
            body,
          },
        )
        updated = await apiFetch<PlayerDetail>(baseUrl, `/api/players/${created.player_id}`, auth)
      } else {
        if (!playerId) throw new Error('Choose a character before editing.')
        updated = await apiFetch<PlayerDetail>(baseUrl, `/api/players/${playerId}`, auth, {
          method: 'PATCH',
          body,
        })
      }
      playerUpserted(updated)
      setPlayerDetail(updated)
      setSelectedPlayerId(updated.player_id)
      setPlayerEditDialog(null)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setPlayerEditDialog((current) => (current ? { ...current, pending: false, error: message } : current))
      pushError('persistence', `Could not ${playerEditDialog.mode === 'create' ? 'create' : 'update'} player: ${message}`)
    }
  }

  const submitPlayerDeleteDialog = async () => {
    if (!playerDeleteDialog) return
    const player = playerDeleteDialog.player
    setPlayerDeleteDialog((current) => (current ? { ...current, pending: true, error: '' } : current))
    try {
      await apiFetch<{ deleted: boolean }>(baseUrl, `/api/players/${player.player_id}`, auth, {
        method: 'DELETE',
      })
      setPlayerDetail(null)
      setSelectedPlayerId((current) => (current === player.player_id ? null : current))
      setPlayerDeleteDialog(null)
      const campaignId = selectedCampaignId ?? player.campaign_id
      if (campaignId) {
        await refreshCampaignWorkspace(campaignId)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setPlayerDeleteDialog((current) => (current ? { ...current, pending: false, error: message } : current))
      pushError('persistence', `Could not delete player: ${message}`)
    }
  }

  return {
    closePlayerDeleteDialog,
    closePlayerEditDialog,
    openCreatePlayerDialog,
    openPlayerDeleteDialog,
    openPlayerEditDialog,
    playerDeleteDialog,
    playerEditDialog,
    setPlayerEditDialog,
    submitPlayerDeleteDialog,
    submitPlayerEditDialog,
  }
}
