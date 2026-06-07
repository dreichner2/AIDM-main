import type {
  Campaign,
  CampaignSegment,
  CampaignWorkspace,
  MapItem,
  Player,
  SessionSummary,
} from './types'

type EntityMap<T> = Record<number, T>

export type WorkspaceCache = {
  campaignIds: number[]
  campaignsById: EntityMap<Campaign>
  sessionIdsByCampaignId: Record<number, number[]>
  sessionsById: EntityMap<SessionSummary>
  playerIdsByCampaignId: Record<number, number[]>
  playersById: EntityMap<Player>
  mapIdsByCampaignId: Record<number, number[]>
  mapsById: EntityMap<MapItem>
  segmentIdsByCampaignId: Record<number, number[]>
  segmentsById: EntityMap<CampaignSegment>
}

export function createWorkspaceCache(): WorkspaceCache {
  return {
    campaignIds: [],
    campaignsById: {},
    sessionIdsByCampaignId: {},
    sessionsById: {},
    playerIdsByCampaignId: {},
    playersById: {},
    mapIdsByCampaignId: {},
    mapsById: {},
    segmentIdsByCampaignId: {},
    segmentsById: {},
  }
}

function uniqueIds(ids: number[]) {
  return [...new Set(ids)]
}

function recordsById<T>(items: T[], idFor: (item: T) => number): EntityMap<T> {
  return Object.fromEntries(items.map((item) => [idFor(item), item]))
}

function mergeEntities<T>(current: EntityMap<T>, items: T[], idFor: (item: T) => number): EntityMap<T> {
  return {
    ...current,
    ...recordsById(items, idFor),
  }
}

function removeKeys<T>(current: EntityMap<T>, idsToRemove: number[]) {
  const next = { ...current }
  idsToRemove.forEach((id) => {
    delete next[id]
  })
  return next
}

function removeCampaignScopedIds(current: Record<number, number[]>, campaignId: number) {
  const next = { ...current }
  delete next[campaignId]
  return next
}

export function cacheRootCampaigns(cache: WorkspaceCache, campaigns: Campaign[]): WorkspaceCache {
  const campaignIds = uniqueIds(campaigns.map((campaign) => campaign.campaign_id))
  const activeCampaignIdSet = new Set(campaignIds)
  const removedCampaignIds = cache.campaignIds.filter((id) => !activeCampaignIdSet.has(id))
  const prunedCache = removedCampaignIds.reduce(
    (current, campaignId) => removeCampaign(current, campaignId),
    cache,
  )

  return {
    ...prunedCache,
    campaignIds,
    campaignsById: mergeEntities(prunedCache.campaignsById, campaigns, (campaign) => campaign.campaign_id),
  }
}

export function cacheCampaignWorkspace(cache: WorkspaceCache, workspace: CampaignWorkspace): WorkspaceCache {
  const campaignId = workspace.campaign.campaign_id
  const campaignIds = cache.campaignIds.includes(campaignId)
    ? cache.campaignIds
    : [campaignId, ...cache.campaignIds]

  return {
    ...cache,
    campaignIds,
    campaignsById: {
      ...cache.campaignsById,
      [campaignId]: workspace.campaign,
    },
    sessionIdsByCampaignId: {
      ...cache.sessionIdsByCampaignId,
      [campaignId]: workspace.sessions.map((session) => session.session_id),
    },
    sessionsById: mergeEntities(cache.sessionsById, workspace.sessions, (session) => session.session_id),
    playerIdsByCampaignId: {
      ...cache.playerIdsByCampaignId,
      [campaignId]: workspace.players.map((player) => player.player_id),
    },
    playersById: mergeEntities(cache.playersById, workspace.players, (player) => player.player_id),
    mapIdsByCampaignId: {
      ...cache.mapIdsByCampaignId,
      [campaignId]: workspace.maps.map((map) => map.map_id),
    },
    mapsById: mergeEntities(cache.mapsById, workspace.maps, (map) => map.map_id),
    segmentIdsByCampaignId: {
      ...cache.segmentIdsByCampaignId,
      [campaignId]: workspace.segments.map((segment) => segment.segment_id),
    },
    segmentsById: mergeEntities(cache.segmentsById, workspace.segments, (segment) => segment.segment_id),
  }
}

export function upsertCampaign(cache: WorkspaceCache, campaign: Campaign): WorkspaceCache {
  return {
    ...cache,
    campaignIds: cache.campaignIds.includes(campaign.campaign_id)
      ? cache.campaignIds
      : [campaign.campaign_id, ...cache.campaignIds],
    campaignsById: {
      ...cache.campaignsById,
      [campaign.campaign_id]: campaign,
    },
  }
}

export function removeCampaign(cache: WorkspaceCache, campaignId: number): WorkspaceCache {
  const sessionIds = cache.sessionIdsByCampaignId[campaignId] ?? []
  const mapIds = cache.mapIdsByCampaignId[campaignId] ?? []
  const segmentIds = cache.segmentIdsByCampaignId[campaignId] ?? []

  return {
    ...cache,
    campaignIds: cache.campaignIds.filter((id) => id !== campaignId),
    campaignsById: removeKeys(cache.campaignsById, [campaignId]),
    sessionIdsByCampaignId: removeCampaignScopedIds(cache.sessionIdsByCampaignId, campaignId),
    sessionsById: removeKeys(cache.sessionsById, sessionIds),
    playerIdsByCampaignId: removeCampaignScopedIds(cache.playerIdsByCampaignId, campaignId),
    mapIdsByCampaignId: removeCampaignScopedIds(cache.mapIdsByCampaignId, campaignId),
    mapsById: removeKeys(cache.mapsById, mapIds),
    segmentIdsByCampaignId: removeCampaignScopedIds(cache.segmentIdsByCampaignId, campaignId),
    segmentsById: removeKeys(cache.segmentsById, segmentIds),
  }
}

export function upsertSession(cache: WorkspaceCache, session: SessionSummary): WorkspaceCache {
  const campaignId = session.campaign_id
  const sessionIds = cache.sessionIdsByCampaignId[campaignId] ?? []
  return {
    ...cache,
    sessionIdsByCampaignId: {
      ...cache.sessionIdsByCampaignId,
      [campaignId]: sessionIds.includes(session.session_id)
        ? sessionIds
        : [session.session_id, ...sessionIds],
    },
    sessionsById: {
      ...cache.sessionsById,
      [session.session_id]: session,
    },
  }
}

export function upsertPlayer(cache: WorkspaceCache, player: Player): WorkspaceCache {
  const campaignId = player.campaign_id
  if (!campaignId) {
    return {
      ...cache,
      playersById: {
        ...cache.playersById,
        [player.player_id]: player,
      },
    }
  }
  const playerIds = cache.playerIdsByCampaignId[campaignId] ?? []
  return {
    ...cache,
    playerIdsByCampaignId: {
      ...cache.playerIdsByCampaignId,
      [campaignId]: playerIds.includes(player.player_id) ? playerIds : [player.player_id, ...playerIds],
    },
    playersById: {
      ...cache.playersById,
      [player.player_id]: player,
    },
  }
}

function selectMany<T>(ids: number[] | undefined, entities: EntityMap<T>) {
  return (ids ?? []).flatMap((id) => {
    const item = entities[id]
    return item ? [item] : []
  })
}

export function selectCampaigns(cache: WorkspaceCache) {
  return selectMany(cache.campaignIds, cache.campaignsById)
}

export function selectCampaign(cache: WorkspaceCache, campaignId: number | null) {
  return campaignId ? cache.campaignsById[campaignId] ?? null : null
}

export function selectSessions(cache: WorkspaceCache, campaignId: number | null) {
  if (!campaignId) return []
  return selectMany(cache.sessionIdsByCampaignId[campaignId], cache.sessionsById)
}

export function selectPlayers(cache: WorkspaceCache, campaignId: number | null) {
  if (!campaignId) return []
  return selectMany(cache.playerIdsByCampaignId[campaignId], cache.playersById)
}

export function selectMaps(cache: WorkspaceCache, campaignId: number | null) {
  if (!campaignId) return []
  return selectMany(cache.mapIdsByCampaignId[campaignId], cache.mapsById)
}

export function selectSegments(cache: WorkspaceCache, campaignId: number | null) {
  if (!campaignId) return []
  return selectMany(cache.segmentIdsByCampaignId[campaignId], cache.segmentsById)
}
