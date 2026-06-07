import { useMemo, useReducer } from 'react'
import type {
  Campaign,
  CampaignWorkspace,
  Player,
  PlayerDetail,
  SessionLogEntry,
  SessionState,
  SessionSummary,
} from './types'
import {
  cacheCampaignWorkspace,
  cacheRootCampaigns,
  createWorkspaceCache,
  removeCampaign,
  selectCampaign,
  selectCampaigns,
  selectMaps,
  selectPlayers,
  selectSegments,
  selectSessions,
  upsertCampaign,
  upsertPlayer,
  upsertSession,
  type WorkspaceCache,
} from './workspaceCache'

type ValueUpdater<T> = T | ((current: T) => T)

type WorkspaceStoreState = {
  cache: WorkspaceCache
  selectedCampaignId: number | null
  selectedSessionId: number | null
  selectedPlayerId: number | null
  playerDetail: PlayerDetail | null
  sessionState: SessionState | null
  logEntries: SessionLogEntry[]
  sessionLogCursor: number | null
  sessionLogHasMore: boolean
  workspaceLoading: boolean
  loadingCampaignId: number | null
  sessionLoading: boolean
}

type WorkspaceStoreInitialSelection = {
  selectedCampaignId: number | null
  selectedSessionId: number | null
  selectedPlayerId: number | null
}

type WorkspaceStoreAction =
  | { type: 'setSelectedCampaignId'; value: ValueUpdater<number | null> }
  | { type: 'setSelectedSessionId'; value: ValueUpdater<number | null> }
  | { type: 'setSelectedPlayerId'; value: ValueUpdater<number | null> }
  | { type: 'setPlayerDetail'; value: ValueUpdater<PlayerDetail | null> }
  | { type: 'setSessionState'; value: ValueUpdater<SessionState | null> }
  | { type: 'setLogEntries'; value: ValueUpdater<SessionLogEntry[]> }
  | { type: 'setSessionLogCursor'; value: ValueUpdater<number | null> }
  | { type: 'setSessionLogHasMore'; value: ValueUpdater<boolean> }
  | { type: 'setWorkspaceLoading'; value: ValueUpdater<boolean> }
  | { type: 'setLoadingCampaignId'; value: ValueUpdater<number | null> }
  | { type: 'setSessionLoading'; value: ValueUpdater<boolean> }
  | { type: 'rootCampaignsLoaded'; campaigns: Campaign[] }
  | { type: 'campaignWorkspaceLoaded'; workspace: CampaignWorkspace }
  | { type: 'campaignUpserted'; campaign: Campaign }
  | { type: 'campaignRemoved'; campaignId: number }
  | { type: 'sessionUpserted'; session: SessionSummary }
  | { type: 'playerUpserted'; player: Player }

function resolveValue<T>(current: T, value: ValueUpdater<T>) {
  return typeof value === 'function' ? (value as (current: T) => T)(current) : value
}

function createInitialState(selection: WorkspaceStoreInitialSelection): WorkspaceStoreState {
  return {
    cache: createWorkspaceCache(),
    selectedCampaignId: selection.selectedCampaignId,
    selectedSessionId: selection.selectedSessionId,
    selectedPlayerId: selection.selectedPlayerId,
    playerDetail: null,
    sessionState: null,
    logEntries: [],
    sessionLogCursor: null,
    sessionLogHasMore: false,
    workspaceLoading: false,
    loadingCampaignId: null,
    sessionLoading: false,
  }
}

function workspaceStoreReducer(
  state: WorkspaceStoreState,
  action: WorkspaceStoreAction,
): WorkspaceStoreState {
  switch (action.type) {
    case 'setSelectedCampaignId':
      return { ...state, selectedCampaignId: resolveValue(state.selectedCampaignId, action.value) }
    case 'setSelectedSessionId':
      return { ...state, selectedSessionId: resolveValue(state.selectedSessionId, action.value) }
    case 'setSelectedPlayerId':
      return { ...state, selectedPlayerId: resolveValue(state.selectedPlayerId, action.value) }
    case 'setPlayerDetail':
      return { ...state, playerDetail: resolveValue(state.playerDetail, action.value) }
    case 'setSessionState':
      return { ...state, sessionState: resolveValue(state.sessionState, action.value) }
    case 'setLogEntries':
      return { ...state, logEntries: resolveValue(state.logEntries, action.value) }
    case 'setSessionLogCursor':
      return { ...state, sessionLogCursor: resolveValue(state.sessionLogCursor, action.value) }
    case 'setSessionLogHasMore':
      return { ...state, sessionLogHasMore: resolveValue(state.sessionLogHasMore, action.value) }
    case 'setWorkspaceLoading':
      return { ...state, workspaceLoading: resolveValue(state.workspaceLoading, action.value) }
    case 'setLoadingCampaignId':
      return { ...state, loadingCampaignId: resolveValue(state.loadingCampaignId, action.value) }
    case 'setSessionLoading':
      return { ...state, sessionLoading: resolveValue(state.sessionLoading, action.value) }
    case 'rootCampaignsLoaded':
      return { ...state, cache: cacheRootCampaigns(state.cache, action.campaigns) }
    case 'campaignWorkspaceLoaded':
      return { ...state, cache: cacheCampaignWorkspace(state.cache, action.workspace) }
    case 'campaignUpserted':
      return { ...state, cache: upsertCampaign(state.cache, action.campaign) }
    case 'campaignRemoved':
      return { ...state, cache: removeCampaign(state.cache, action.campaignId) }
    case 'sessionUpserted':
      return { ...state, cache: upsertSession(state.cache, action.session) }
    case 'playerUpserted':
      return { ...state, cache: upsertPlayer(state.cache, action.player) }
    default:
      return state
  }
}

export function useWorkspaceStore(selection: WorkspaceStoreInitialSelection) {
  const [state, dispatch] = useReducer(
    workspaceStoreReducer,
    selection,
    createInitialState,
  )

  const actions = useMemo(
    () => ({
      setSelectedCampaignId: (value: ValueUpdater<number | null>) =>
        dispatch({ type: 'setSelectedCampaignId', value }),
      setSelectedSessionId: (value: ValueUpdater<number | null>) =>
        dispatch({ type: 'setSelectedSessionId', value }),
      setSelectedPlayerId: (value: ValueUpdater<number | null>) =>
        dispatch({ type: 'setSelectedPlayerId', value }),
      setPlayerDetail: (value: ValueUpdater<PlayerDetail | null>) =>
        dispatch({ type: 'setPlayerDetail', value }),
      setSessionState: (value: ValueUpdater<SessionState | null>) =>
        dispatch({ type: 'setSessionState', value }),
      setLogEntries: (value: ValueUpdater<SessionLogEntry[]>) =>
        dispatch({ type: 'setLogEntries', value }),
      setSessionLogCursor: (value: ValueUpdater<number | null>) =>
        dispatch({ type: 'setSessionLogCursor', value }),
      setSessionLogHasMore: (value: ValueUpdater<boolean>) =>
        dispatch({ type: 'setSessionLogHasMore', value }),
      setWorkspaceLoading: (value: ValueUpdater<boolean>) =>
        dispatch({ type: 'setWorkspaceLoading', value }),
      setLoadingCampaignId: (value: ValueUpdater<number | null>) =>
        dispatch({ type: 'setLoadingCampaignId', value }),
      setSessionLoading: (value: ValueUpdater<boolean>) =>
        dispatch({ type: 'setSessionLoading', value }),
      rootCampaignsLoaded: (campaigns: Campaign[]) =>
        dispatch({ type: 'rootCampaignsLoaded', campaigns }),
      campaignWorkspaceLoaded: (workspace: CampaignWorkspace) =>
        dispatch({ type: 'campaignWorkspaceLoaded', workspace }),
      campaignUpserted: (campaign: Campaign) =>
        dispatch({ type: 'campaignUpserted', campaign }),
      campaignRemoved: (campaignId: number) =>
        dispatch({ type: 'campaignRemoved', campaignId }),
      sessionUpserted: (session: SessionSummary) =>
        dispatch({ type: 'sessionUpserted', session }),
      playerUpserted: (player: Player) =>
        dispatch({ type: 'playerUpserted', player }),
    }),
    [],
  )

  const campaigns = useMemo(() => selectCampaigns(state.cache), [state.cache])
  const campaign = useMemo(
    () => selectCampaign(state.cache, state.selectedCampaignId),
    [state.cache, state.selectedCampaignId],
  )
  const sessions = useMemo(
    () => selectSessions(state.cache, state.selectedCampaignId),
    [state.cache, state.selectedCampaignId],
  )
  const players = useMemo(
    () => selectPlayers(state.cache, state.selectedCampaignId),
    [state.cache, state.selectedCampaignId],
  )
  const maps = useMemo(
    () => selectMaps(state.cache, state.selectedCampaignId),
    [state.cache, state.selectedCampaignId],
  )
  const segments = useMemo(
    () => selectSegments(state.cache, state.selectedCampaignId),
    [state.cache, state.selectedCampaignId],
  )

  return {
    ...state,
    campaigns,
    campaign,
    sessions,
    players,
    maps,
    segments,
    ...actions,
  }
}
