import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import {
  ArrowDown,
  ChevronDown,
  Circle,
  ClipboardList,
  Download,
  ExternalLink,
  Flame,
  Lock,
  Maximize2,
  Menu,
  Minimize2,
  MoreHorizontal,
  Plus,
  Radio,
  Settings,
  Share2,
  Sun,
  UserCircle,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react'
import { io, type Socket } from 'socket.io-client'
import { ApiClientError, apiFetch, normalizeBaseUrl } from './api'
import './App.css'
import type {
  BetaSummary,
  Campaign,
  CampaignCanon,
  CampaignWorkspace,
  CampaignSegment,
  Health,
  JsonRecord,
  LlmRuntimeConfig,
  MapItem,
  Player,
  PlayerDetail,
  RulesHint,
  SessionLogEntry,
  SessionLogResponse,
  SessionEventsResponse,
  SessionState,
  SessionSummary,
  SocketErrorPayload,
  StreamingTurn,
  TimelineEntry,
  TimelineRole,
  TtsRuntimeConfig,
  World,
} from './types'

const DEFAULT_BASE_URL =
  import.meta.env.VITE_AIDM_API_BASE_URL ?? 'http://127.0.0.1:5050'

const loadDiceRollDialog = () => import('./DiceRollDialog')
const DiceRollDialog = lazy(loadDiceRollDialog)

function preloadDiceRollDialog() {
  void loadDiceRollDialog()
}

type MainTab = 'turns' | 'dm' | 'notes'
type InspectorTab = 'party' | 'map' | 'canon' | 'inventory'
type ComposerMode = 'action' | 'roll' | 'ability' | 'item' | 'emote' | 'ooc'
type ThemeMode = 'dark' | 'light'
type TtsPlaybackStatus = 'off' | 'ready' | 'queued' | 'requesting' | 'speaking' | 'failed'

type CampaignCard = {
  id: number
  title: string
  meta: string
  avatar: string
}

type CampaignSessionMeta = {
  count: number
  updatedAt: string | null
  latestSessionId: number | null
}

type SessionCard = {
  id: number
  title: string
  meta: string
}

type CreateCampaignForm = {
  title: string
  description: string
  worldName: string
}

type RuntimeSettingsForm = {
  baseUrl: string
  authToken: string
}

type DiceRollState = {
  die: string
  result: number
  rollKey: number
  status: 'rolling' | 'sending'
}

const DICE_OPTIONS = ['d4', 'd6', 'd8', 'd10', 'd12', 'd20', 'd100']
const TTS_AUDIO_MIME = 'audio/mpeg'
const TTS_MIN_PARTIAL_FLUSH_CHARS = 48
const TTS_FORCE_PARTIAL_FLUSH_CHARS = 180
const TTS_PARTIAL_FLUSH_DELAY_MS = 2500
const TTS_RECENT_TEXT_DEDUPE_MS = 120_000

const COMPOSER_PREFIX_PATTERNS = [
  /^\[OOC\]\s*/i,
  /^I roll a d(?:4|6|8|10|12|20|100):\s*/i,
  /^\/emote\s*/i,
  /^[^:\n]{1,80}\s+attempts an ability check:\s*/i,
  /^[^:\n]{1,80}\s+uses\s*/i,
]

type InventoryRow = {
  item: string
  count: string
  weight: string
  icon: string
  weightValue: number | null
}

type StatBlock = {
  hp: string
  ac: string
  init: string
  speed: string
  abilities: Array<[string, string, string]>
  proficiency: string
  inspiration: boolean
}

type XpProgress = {
  current: number
  max: number
  percent: number
  label: string
}

type TtsQueueItem = {
  text: string
  audioUrlPromise: Promise<string | null>
  controller: AbortController
  cleanup?: () => void
  streamDone?: Promise<void>
}

type MapPanelMeta = {
  explored: string
  threat: string
  threatTone: 'low' | 'medium' | 'high'
  weather: string
}

type ThinIconName =
  | 'archive'
  | 'bolt'
  | 'book'
  | 'briefcase'
  | 'chevron'
  | 'cloud'
  | 'cog'
  | 'cube'
  | 'dice'
  | 'dot'
  | 'map'
  | 'refresh'
  | 'send'
  | 'settings'
  | 'smile'
  | 'spark'
  | 'turns'

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stringValue(value: unknown, fallback = '') {
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return fallback
}

function formatDateTime(value: string | null) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Not recorded'
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatClock(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function formatShortAge(value: string | null) {
  if (!value) return 'No timestamp'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'No timestamp'
  const diffMs = Date.now() - date.getTime()
  const absMs = Math.max(0, diffMs)
  const minutes = Math.floor(absMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  const months = Math.floor(days / 30)
  return `${Math.max(1, months)}mo ago`
}

function formatDurationFrom(value: string | null, nowMs: number) {
  if (!value) return 'No session'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'No session'
  const seconds = Math.max(0, Math.floor((nowMs - date.getTime()) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainingSeconds = seconds % 60
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`
  return `${minutes}m ${String(remainingSeconds).padStart(2, '0')}s`
}

function latestTimestamp(values: Array<string | null | undefined>): string | null {
  let latest: string | null = null
  let latestMs = 0
  values.forEach((value) => {
    if (!value) return
    const time = new Date(value).getTime()
    if (!Number.isNaN(time) && time >= latestMs) {
      latestMs = time
      latest = value
    }
  })
  return latest
}

function snapshotRecord(session: SessionSummary | null | undefined) {
  return isRecord(session?.state_snapshot) ? session.state_snapshot : {}
}

function sessionDisplayName(session: SessionSummary, fallbackPrefix: string | number | null) {
  const snapshot = snapshotRecord(session)
  return (
    stringValue(session.display_name) ||
    stringValue(snapshot.name) ||
    stringValue(snapshot.title) ||
    `S${fallbackPrefix ?? '—'}E${session.session_id}`
  )
}

function sessionMetaFromCampaign(campaign: Campaign): CampaignSessionMeta {
  return {
    count: campaign.session_count ?? 0,
    updatedAt: campaign.latest_activity_at ?? campaign.created_at,
    latestSessionId: campaign.latest_session_id ?? null,
  }
}

function truncateText(value: string, maxLength: number) {
  const compact = value.replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) return compact
  return `${compact.slice(0, maxLength - 1).trim()}…`
}

function stripMarkdown(value: string) {
  return value
    .replace(/\*\*/g, '')
    .replace(/\*/g, '')
    .replace(/---+/g, '')
    .replace(/#+\s*/g, '')
}

function cleanNarrationText(value: string) {
  return stripMarkdown(value.replace(/<thought>[\s\S]*?(?:<\/thought>|$)/gi, ''))
    .replace(/\s+/g, ' ')
    .trim()
}

function parsePositiveInt(value: string | null) {
  if (!value) return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function stripComposerCommand(value: string) {
  let next = value.trimStart()
  COMPOSER_PREFIX_PATTERNS.forEach((pattern) => {
    next = next.replace(pattern, '')
  })
  return next
}

function composerModeLabel(mode: ComposerMode, die: string) {
  if (mode === 'ooc') return 'Out of Character'
  if (mode === 'roll') return `Roll ${die.toUpperCase()}`
  if (mode === 'ability') return 'Ability Check'
  if (mode === 'item') return 'Item Use'
  if (mode === 'emote') return 'Emote'
  return 'In Character'
}

function composerTextForMode(
  mode: ComposerMode,
  current: string,
  characterName: string,
  die: string,
) {
  const body = stripComposerCommand(current)
  const suffix = body ? body : ''
  if (mode === 'roll') return `I roll a ${die}: ${suffix}`
  if (mode === 'ooc') return `[OOC] ${suffix}`
  if (mode === 'ability') return `${characterName} attempts an ability check: ${suffix}`
  if (mode === 'item') return `${characterName} uses ${suffix}`
  if (mode === 'emote') return `/emote ${suffix}`
  return suffix
}

function dieSides(die: string) {
  const parsed = Number(die.replace(/^d/i, ''))
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 20
}

function rollDie(die: string) {
  const sides = dieSides(die)
  if (typeof window.crypto?.getRandomValues === 'function') {
    const value = new Uint32Array(1)
    window.crypto.getRandomValues(value)
    return (value[0] % sides) + 1
  }
  return Math.floor(Math.random() * sides) + 1
}

function diceRollMessage(die: string, result: number) {
  return `I roll a ${die.toLowerCase()}: ${result}`
}

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat(undefined, {
    notation: value >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value)
}

function numberValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value.replace(/[^0-9.-]/g, ''))
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function metadataTurnId(metadata: JsonRecord) {
  const parsed = numberValue(metadata.turn_id)
  return parsed !== null && Number.isInteger(parsed) ? parsed : null
}

function ttsDedupeKeysForText(text: string, turnId: number | null) {
  const cleanText = cleanNarrationText(text)
  const keys: string[] = []
  if (turnId !== null) {
    keys.push(`turn:${turnId}`)
  }
  if (cleanText) {
    keys.push(`text:${hashString(cleanText)}:${cleanText.length}`)
  }
  return keys
}

function ttsDedupeKeysForEntry(entry: TimelineEntry) {
  return ttsDedupeKeysForText(entry.text, metadataTurnId(entry.metadata))
}

function collectRecords(value: unknown): JsonRecord[] {
  if (!isRecord(value)) return []
  const records: JsonRecord[] = [value]
  ;[
    'stats',
    'ability_scores',
    'abilities',
    'attributes',
    'combat',
    'derived',
    'health',
    'character',
  ].forEach((key) => {
    if (isRecord(value[key])) records.push(value[key] as JsonRecord)
  })
  return records
}

function findValue(records: JsonRecord[], keys: string[]) {
  for (const record of records) {
    for (const key of keys) {
      if (record[key] !== undefined && record[key] !== null && record[key] !== '') {
        return record[key]
      }
    }
  }
  return null
}

function pluralize(value: number, singular: string, plural = `${singular}s`) {
  return `${value} ${value === 1 ? singular : plural}`
}

function providerLabel(value: string) {
  const normalized = value.trim().toLowerCase()
  if (!normalized) return 'Unknown'
  if (normalized === 'nvidia') return 'NVIDIA'
  if (normalized === 'openai') return 'OpenAI'
  if (normalized === 'gemini') return 'Gemini'
  if (normalized === 'kimi') return 'Kimi'
  if (normalized === 'fallback') return 'Fallback'
  return value
}

function hashString(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index)
    hash |= 0
  }
  return Math.abs(hash)
}

function avatarDataUri(seed: string, variant: 'campaign' | 'character' = 'campaign') {
  const palettes = [
    ['#4b2d1f', '#f36b2e', '#f4d8a8'],
    ['#172a32', '#78a9d8', '#d6f0ff'],
    ['#2d2117', '#c79752', '#f0d49c'],
    ['#1e2825', '#8bb29e', '#d7e7dc'],
    ['#2b2027', '#b86d82', '#f3cbd4'],
  ]
  const hash = hashString(seed || variant)
  const [base, accent, light] = palettes[hash % palettes.length]
  const angle = 28 + (hash % 46)
  const glyph = variant === 'character' ? 'M' : 'A'
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
      <defs>
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="${light}" stop-opacity=".28"/>
          <stop offset=".42" stop-color="${accent}" stop-opacity=".42"/>
          <stop offset="1" stop-color="${base}"/>
        </linearGradient>
        <filter id="s"><feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#000" flood-opacity=".34"/></filter>
      </defs>
      <rect width="96" height="96" rx="8" fill="${base}"/>
      <path d="M-10 ${72 - angle} C22 14, 70 16, 106 ${angle}" fill="none" stroke="${accent}" stroke-width="18" stroke-opacity=".34"/>
      <path d="M16 76 L48 12 L80 76 Z" fill="url(#g)" filter="url(#s)"/>
      <path d="M25 68 L48 24 L71 68 Z" fill="none" stroke="${light}" stroke-width="2" stroke-opacity=".36"/>
      <text x="48" y="61" text-anchor="middle" font-family="Inter, Arial" font-size="24" font-weight="500" fill="${light}" opacity=".82">${glyph}</text>
    </svg>
  `
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

function normalizeInventory(value: unknown): InventoryRow[] {
  const source = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.items)
      ? value.items
      : []
  const iconFor = (item: string, index: number) => {
    const normalized = item.toLowerCase()
    if (normalized.includes('sword') || normalized.includes('blade')) return 'sword'
    if (normalized.includes('shield')) return 'shield'
    if (normalized.includes('potion') || normalized.includes('vial')) return 'potion'
    if (normalized.includes('armor') || normalized.includes('mail')) return 'armor'
    if (normalized.includes('ration') || normalized.includes('food')) return 'ration'
    return ['sword', 'shield', 'potion', 'armor', 'ration'][index % 5]
  }
  return source.map((entry, index) => {
    if (typeof entry === 'string') {
      return { item: entry, count: '1', weight: '—', icon: iconFor(entry, index), weightValue: null }
    }
    if (!isRecord(entry)) {
      return { item: `Item ${index + 1}`, count: '1', weight: '—', icon: 'ration', weightValue: null }
    }
    const item =
      stringValue(entry.name) ||
      stringValue(entry.item) ||
      stringValue(entry.label) ||
      `Item ${index + 1}`
    const countNumber = numberValue(entry.quantity ?? entry.count) ?? 1
    const weightNumber = numberValue(entry.weight)
    const weightValue =
      weightNumber === null ? null : Math.round(weightNumber * countNumber * 10) / 10
    return {
      item,
      count: stringValue(entry.quantity ?? entry.count, '1'),
      weight: weightNumber === null ? '—' : `${weightValue} lb`,
      icon: stringValue(entry.icon, iconFor(item, index)),
      weightValue,
    }
  })
}

function normalizeStats(statsValue: unknown, sheetValue: unknown, level: number | null): StatBlock {
  const records = [...collectRecords(statsValue), ...collectRecords(sheetValue)]
  const scoreFor = (longKey: string, shortKey: string) =>
    numberValue(findValue(records, [longKey, shortKey, `${longKey}_score`, `${shortKey}_score`]))
  const statLabel = (keys: string[], fallback = '—') =>
    stringValue(findValue(records, keys), fallback)
  const hpCurrent = statLabel(['current_hp', 'hp_current', 'hp', 'hit_points', 'currentHitPoints'])
  const hpMax = statLabel(['max_hp', 'hp_max', 'max_hit_points', 'maxHitPoints'])
  const hp = hpMax !== '—' && hpMax !== hpCurrent ? `${hpCurrent} / ${hpMax}` : hpCurrent
  const abilityEntries: Array<[string, string, string]> = [
    ['STR', 'strength', 'str'],
    ['DEX', 'dexterity', 'dex'],
    ['CON', 'constitution', 'con'],
    ['INT', 'intelligence', 'int'],
    ['WIS', 'wisdom', 'wis'],
    ['CHA', 'charisma', 'cha'],
  ].map(([label, longKey, shortKey]) => {
    const score = scoreFor(longKey, shortKey)
    if (score === null) return [label, '—', '—']
    const modifier = Math.floor((score - 10) / 2)
    return [label, String(score), modifier >= 0 ? `+${modifier}` : String(modifier)]
  })
  const proficiencyValue = statLabel(['proficiency_bonus', 'proficiency', 'prof_bonus'])

  return {
    hp,
    ac: statLabel(['ac', 'armor_class', 'armorClass']),
    init: statLabel(['initiative', 'init']),
    speed: statLabel(['speed', 'movement', 'walk_speed']),
    abilities: abilityEntries,
    proficiency: proficiencyValue !== '—' ? proficiencyValue : level ? `+${2 + Math.floor((level - 1) / 4)}` : '—',
    inspiration: Boolean(findValue(records, ['inspiration', 'inspired'])),
  }
}

function displayStatValue(value: string) {
  return value
}

function normalizeXp(value: unknown, level: number | string): XpProgress {
  const records = collectRecords(value)
  const current = numberValue(findValue(records, ['xp', 'experience', 'current_xp'])) ?? 0
  const max =
    numberValue(findValue(records, ['xp_to_next', 'next_level_xp', 'max_xp'])) ??
    Math.max(300, Number(level) * 300)
  const percent = max > 0 ? Math.min(100, Math.round((current / max) * 100)) : 0
  return {
    current,
    max,
    percent,
    label: `${formatCompactNumber(current)} / ${formatCompactNumber(max)} XP`,
  }
}

function inventoryCapacity(value: unknown) {
  const records = collectRecords(value)
  return numberValue(findValue(records, ['carrying_capacity', 'capacity', 'max_weight', 'maxWeight']))
}

function buildMapMeta(map: MapItem | undefined, segment: CampaignSegment | null): MapPanelMeta {
  const data = map?.map_data ?? {}
  const exploredNumber =
    numberValue(data.explored_percent ?? data.exploredPercent ?? data.explored ?? data.progress) ??
    (map ? 0 : null)
  const rawThreat =
    stringValue(data.threat_level) ||
    stringValue(data.threat) ||
    (segment?.tags.toLowerCase().includes('high') ? 'High' : '') ||
    (segment?.is_triggered ? 'Elevated' : 'Unknown')
  const normalizedThreat = rawThreat.toLowerCase()
  const threatTone =
    normalizedThreat.includes('high') || normalizedThreat.includes('danger')
      ? 'high'
      : normalizedThreat.includes('medium') || normalizedThreat.includes('elevated')
        ? 'medium'
        : 'low'
  return {
    explored: exploredNumber === null ? '—' : `${Math.round(exploredNumber)}%`,
    threat: rawThreat,
    threatTone,
    weather: stringValue(data.weather) || stringValue(data.climate) || 'Not recorded',
  }
}

function turnNumber(entry: TimelineEntry, fallbackIndex: number) {
  const metadataTurn = entry.metadata.turn_id
  return typeof metadataTurn === 'number' ? metadataTurn : fallbackIndex + 1
}

function speakerDetail(entry: TimelineEntry, selectedPlayer: Player | null) {
  if (entry.role === 'dm') return 'Narration'
  if (entry.role === 'system') return 'System'
  if (selectedPlayer && entry.speaker === selectedPlayer.character_name) {
    return `${selectedPlayer.race || 'Adventurer'} ${selectedPlayer.char_class || selectedPlayer.class_ || ''}`.trim()
  }
  return 'Player'
}

function stripSpeakerPrefix(message: string, speaker: string) {
  const prefix = `${speaker}:`
  return message.startsWith(prefix) ? message.slice(prefix.length).trim() : message
}

function timelineFromLog(entry: SessionLogEntry): TimelineEntry {
  let role: TimelineRole = entry.entry_type === 'player' ? 'player' : 'dm'
  let speaker = role === 'player' ? 'Player' : 'DM'
  let text = entry.message

  if (text.startsWith('**')) {
    role = 'system'
    speaker = 'System'
    text = text.replaceAll('**', '')
  } else if (text.startsWith('DM:')) {
    speaker = 'DM'
    text = stripSpeakerPrefix(text, 'DM')
  } else if (role === 'player' && text.includes(':')) {
    const splitIndex = text.indexOf(':')
    speaker = text.slice(0, splitIndex)
    text = text.slice(splitIndex + 1).trim()
  }

  return {
    id: `log-${entry.id}`,
    role,
    speaker,
    text,
    timestamp: entry.timestamp,
    metadata: entry.metadata ?? {},
  }
}

function socketMessage(payload: SocketErrorPayload) {
  return payload.error ?? payload.message ?? payload.error_code ?? 'Socket error'
}

function supportsStreamingTtsAudio() {
  return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(TTS_AUDIO_MIME)
}

async function ttsErrorMessage(response: Response) {
  let message = `TTS request failed with status ${response.status}`
  try {
    const payload = await response.json()
    if (payload && typeof payload === 'object' && 'error' in payload) {
      message = String((payload as JsonRecord).error)
    }
  } catch {
    // Keep the status-based message when the server did not return JSON.
  }
  return message
}

function ttsPlaybackErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) return error.message
  if (error instanceof Event) return error.type ? `Audio ${error.type}` : 'Audio playback error'
  return String(error || 'Audio playback error')
}

function waitForSourceBufferIdle(sourceBuffer: SourceBuffer, signal: AbortSignal) {
  if (!sourceBuffer.updating) return Promise.resolve()

  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      sourceBuffer.removeEventListener('updateend', handleUpdateEnd)
      sourceBuffer.removeEventListener('error', handleError)
      signal.removeEventListener('abort', handleAbort)
    }
    const handleUpdateEnd = () => {
      cleanup()
      resolve()
    }
    const handleError = () => {
      cleanup()
      reject(new Error('TTS audio buffer failed to update.'))
    }
    const handleAbort = () => {
      cleanup()
      reject(new Error('TTS request aborted.'))
    }

    sourceBuffer.addEventListener('updateend', handleUpdateEnd)
    sourceBuffer.addEventListener('error', handleError)
    signal.addEventListener('abort', handleAbort, { once: true })
  })
}

function exactArrayBuffer(bytes: Uint8Array) {
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  return copy.buffer
}

async function appendTtsAudioChunk(
  sourceBuffer: SourceBuffer,
  bytes: Uint8Array,
  signal: AbortSignal,
) {
  if (signal.aborted) throw new Error('TTS request aborted.')
  await waitForSourceBufferIdle(sourceBuffer, signal)
  sourceBuffer.appendBuffer(exactArrayBuffer(bytes))
  await waitForSourceBufferIdle(sourceBuffer, signal)
}

function createStreamingTtsSource(
  requestAudio: () => Promise<Response>,
  controller: AbortController,
  onError: (message: string) => void,
) {
  if (!supportsStreamingTtsAudio()) return null

  const mediaSource = new MediaSource()
  const audioUrl = URL.createObjectURL(mediaSource)
  let sourceBuffer: SourceBuffer | null = null
  let cleaned = false

  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    try {
      if (sourceBuffer?.updating) {
        sourceBuffer.abort()
      }
      if (mediaSource.readyState === 'open') {
        mediaSource.endOfStream()
      }
    } catch {
      // The audio element may already have torn the MediaSource down.
    }
    URL.revokeObjectURL(audioUrl)
  }

  const streamDone = new Promise<void>((resolve) => {
    mediaSource.addEventListener(
      'sourceopen',
      () => {
        void (async () => {
          try {
            sourceBuffer = mediaSource.addSourceBuffer(TTS_AUDIO_MIME)
            sourceBuffer.mode = 'sequence'

            const response = await requestAudio()
            if (!response.ok) {
              throw new Error(await ttsErrorMessage(response))
            }

            const reader = response.body?.getReader()
            if (!reader) {
              const bytes = new Uint8Array(await response.arrayBuffer())
              await appendTtsAudioChunk(sourceBuffer, bytes, controller.signal)
            } else {
              while (true) {
                const { done, value } = await reader.read()
                if (done) break
                if (value) {
                  await appendTtsAudioChunk(sourceBuffer, value, controller.signal)
                }
              }
            }

            await waitForSourceBufferIdle(sourceBuffer, controller.signal)
            if (mediaSource.readyState === 'open') {
              mediaSource.endOfStream()
            }
          } catch (error) {
            if (!controller.signal.aborted) {
              onError(error instanceof Error ? error.message : String(error))
              try {
                if (mediaSource.readyState === 'open') {
                  mediaSource.endOfStream('network')
                }
              } catch {
                // Ignore cleanup errors after a failed stream.
              }
            }
          } finally {
            resolve()
          }
        })()
      },
      { once: true },
    )
  })

  return {
    audioUrl,
    cleanup,
    streamDone,
  }
}

function ttsFlushLength(text: string, forcePartial: boolean) {
  if (!text.trim()) return 0

  const sentenceMatch = text.match(/.*?(?:[.!?]+["'*\])_]*(?=\s|$)|[\n]+)/s)
  if (sentenceMatch) return sentenceMatch[0].length

  const limit = Math.min(text.length, TTS_FORCE_PARTIAL_FLUSH_CHARS)
  if (text.length >= TTS_FORCE_PARTIAL_FLUSH_CHARS || forcePartial) {
    const windowText = text.slice(0, limit)
    const naturalBreak = Math.max(
      windowText.lastIndexOf(','),
      windowText.lastIndexOf(';'),
      windowText.lastIndexOf(':'),
      windowText.lastIndexOf(' - '),
    )
    if (naturalBreak >= TTS_MIN_PARTIAL_FLUSH_CHARS) return naturalBreak + 1

    const wordBreak = windowText.lastIndexOf(' ')
    if (wordBreak >= TTS_MIN_PARTIAL_FLUSH_CHARS) return wordBreak + 1
    if (forcePartial && windowText.trim().length >= TTS_MIN_PARTIAL_FLUSH_CHARS) return limit
  }

  return 0
}

function StatusDot({
  label,
  tone = 'good',
}: {
  label: string
  tone?: 'good' | 'neutral' | 'warn'
}) {
  return (
    <span className={`status-dot ${tone}`}>
      <Circle size={8} fill="currentColor" />
      {label}
    </span>
  )
}

function ThinIcon({
  name,
  size = 18,
  className,
}: {
  name: ThinIconName
  size?: number
  className?: string
}) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    strokeWidth: 1.35,
  }
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
    >
      {name === 'archive' ? (
        <>
          <path {...common} d="M5 6.5h14v12H5z" />
          <path {...common} d="M8 6.5V4h8v2.5M9 10h6" />
        </>
      ) : null}
      {name === 'bolt' ? <path {...common} d="M13 2 5.5 13h5L9 22l8-12h-5z" /> : null}
      {name === 'book' ? (
        <>
          <path {...common} d="M6 4.5h8.5A2.5 2.5 0 0 1 17 7v12H8.5A2.5 2.5 0 0 1 6 16.5z" />
          <path {...common} d="M17 7h1.5v12H17M9 8h4" />
        </>
      ) : null}
      {name === 'briefcase' ? (
        <>
          <path {...common} d="M4.5 8h15v10.5h-15z" />
          <path {...common} d="M9 8V5.5h6V8M4.5 12h15" />
        </>
      ) : null}
      {name === 'chevron' ? <path {...common} d="m7 9 5 5 5-5" /> : null}
      {name === 'cloud' ? (
        <path {...common} d="M7.5 18h9a4 4 0 0 0 .2-8 5.6 5.6 0 0 0-10.7 1.8A3.2 3.2 0 0 0 7.5 18Z" />
      ) : null}
      {name === 'cog' ? (
        <>
          <circle {...common} cx="12" cy="12" r="2.8" />
          <path {...common} d="M12 3.5v2M12 18.5v2M4.6 7.8l1.7 1M17.7 15.2l1.7 1M4.6 16.2l1.7-1M17.7 8.8l1.7-1M3.5 12h2M18.5 12h2" />
        </>
      ) : null}
      {name === 'cube' ? (
        <>
          <path {...common} d="m12 3 7 4v10l-7 4-7-4V7z" />
          <path {...common} d="m5 7 7 4 7-4M12 11v10" />
        </>
      ) : null}
      {name === 'dice' ? (
        <>
          <rect {...common} x="5" y="5" width="14" height="14" rx="2" />
          <circle cx="9" cy="9" r="1" fill="currentColor" />
          <circle cx="15" cy="15" r="1" fill="currentColor" />
          <circle cx="15" cy="9" r="1" fill="currentColor" />
          <circle cx="9" cy="15" r="1" fill="currentColor" />
        </>
      ) : null}
      {name === 'dot' ? <circle cx="12" cy="12" r="2.3" fill="currentColor" /> : null}
      {name === 'map' ? (
        <>
          <path {...common} d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2z" />
          <path {...common} d="M9 4v14M15 6v14" />
        </>
      ) : null}
      {name === 'refresh' ? (
        <>
          <path {...common} d="M18.5 8.5A7 7 0 0 0 6 6.3L4.5 8.5" />
          <path {...common} d="M4.5 4.5v4h4M5.5 15.5A7 7 0 0 0 18 17.7l1.5-2.2" />
          <path {...common} d="M19.5 19.5v-4h-4" />
        </>
      ) : null}
      {name === 'send' ? <path {...common} d="M4 12.5 20 4l-5.8 16-3.1-6.9zM11.1 13.1 20 4" /> : null}
      {name === 'settings' ? (
        <>
          <circle {...common} cx="12" cy="12" r="3" />
          <path {...common} d="M12 4.5v2M12 17.5v2M5.6 6.7 7 8.1M17 15.9l1.4 1.4M4.5 12h2M17.5 12h2M5.6 17.3 7 15.9M17 8.1l1.4-1.4" />
        </>
      ) : null}
      {name === 'smile' ? (
        <>
          <circle {...common} cx="12" cy="12" r="8" />
          <path {...common} d="M8.8 14.2a4.4 4.4 0 0 0 6.4 0" />
          <path {...common} d="M9 10h.01M15 10h.01" />
        </>
      ) : null}
      {name === 'spark' ? <path {...common} d="m12 3 1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9z" /> : null}
      {name === 'turns' ? (
        <>
          <path {...common} d="M6 7h9a3 3 0 0 1 0 6H8" />
          <path {...common} d="m9 4-3 3 3 3M18 17H9" />
        </>
      ) : null}
    </svg>
  )
}

function ToolbarButton({
  children,
  icon,
  onClick,
  title,
}: {
  children?: React.ReactNode
  icon: React.ReactNode
  onClick?: () => void
  title: string
}) {
  return (
    <button
      type="button"
      className="toolbar-button"
      onClick={onClick}
      title={title}
      aria-label={title}
    >
      {icon}
      {children ? <span>{children}</span> : null}
    </button>
  )
}

function Thumbnail({
  index,
  selected,
  src,
  title,
}: {
  index: number
  selected?: boolean
  src: string
  title: string
}) {
  return (
    <span className={`thumb thumb-${index} ${selected ? 'selected-thumb' : ''}`}>
      <img src={src} alt="" aria-hidden="true" />
      <span className="thumb-letter">{title.slice(0, 1).toUpperCase()}</span>
    </span>
  )
}

function NavItem({
  icon,
  label,
  onClick,
  selected,
}: {
  icon: React.ReactNode
  label: string
  onClick?: () => void
  selected?: boolean
}) {
  return (
    <button
      type="button"
      className={`nav-item ${selected ? 'active' : ''}`}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}

function App() {
  const [baseUrl, setBaseUrl] = useState(() =>
    normalizeBaseUrl(localStorage.getItem('aidm:baseUrl') ?? DEFAULT_BASE_URL),
  )
  const [authToken, setAuthToken] = useState(() => localStorage.getItem('aidm:authToken') ?? '')
  const [health, setHealth] = useState<Health | null>(null)
  const [llmConfig, setLlmConfig] = useState<LlmRuntimeConfig | null>(null)
  const [ttsConfig, setTtsConfig] = useState<TtsRuntimeConfig | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(() => localStorage.getItem('aidm:ttsEnabled') === 'true')
  const [ttsSpeaking, setTtsSpeaking] = useState(false)
  const [ttsQueueCount, setTtsQueueCount] = useState(0)
  const [ttsStatus, setTtsStatus] = useState<TtsPlaybackStatus>(() =>
    localStorage.getItem('aidm:ttsEnabled') === 'true' ? 'ready' : 'off',
  )
  const [runtimePending, setRuntimePending] = useState(false)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [campaignSessionMeta, setCampaignSessionMeta] = useState<
    Record<number, CampaignSessionMeta>
  >({})
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(() =>
    parsePositiveInt(
      new URLSearchParams(window.location.search).get('campaign') ??
        localStorage.getItem('aidm:selectedCampaignId'),
    ),
  )
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(() =>
    parsePositiveInt(
      new URLSearchParams(window.location.search).get('session') ??
        localStorage.getItem('aidm:selectedSessionId'),
    ),
  )
  const [players, setPlayers] = useState<Player[]>([])
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(() =>
    parsePositiveInt(
      new URLSearchParams(window.location.search).get('player') ??
        localStorage.getItem('aidm:selectedPlayerId'),
    ),
  )
  const [playerDetail, setPlayerDetail] = useState<PlayerDetail | null>(null)
  const [maps, setMaps] = useState<MapItem[]>([])
  const [segments, setSegments] = useState<CampaignSegment[]>([])
  const [sessionState, setSessionState] = useState<SessionState | null>(null)
  const [logEntries, setLogEntries] = useState<SessionLogEntry[]>([])
  const [metrics, setMetrics] = useState<BetaSummary | null>(null)
  const [socketStatus, setSocketStatus] = useState('idle')
  const [sendPending, setSendPending] = useState(false)
  const [actionText, setActionText] = useState('')
  const [composerMode, setComposerMode] = useState<ComposerMode>('action')
  const [selectedDie, setSelectedDie] = useState('d20')
  const [diceRoll, setDiceRoll] = useState<DiceRollState | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [optimisticEntries, setOptimisticEntries] = useState<TimelineEntry[]>([])
  const [streamingTurn, setStreamingTurn] = useState<StreamingTurn | null>(null)
  const [mainTab, setMainTab] = useState<MainTab>('turns')
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('party')
  const [campaignFilter, setCampaignFilter] = useState('')
  const [expandedTurnIds, setExpandedTurnIds] = useState<Set<string>>(() => new Set())
  const [showJumpToLatest, setShowJumpToLatest] = useState(false)
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [fullscreenFallback, setFullscreenFallback] = useState(false)
  const [theme, setTheme] = useState<ThemeMode>(() =>
    localStorage.getItem('aidm:theme') === 'light' ? 'light' : 'dark',
  )
  const [createCampaignOpen, setCreateCampaignOpen] = useState(false)
  const [createCampaignPending, setCreateCampaignPending] = useState(false)
  const [createCampaignError, setCreateCampaignError] = useState('')
  const [runtimeSettingsOpen, setRuntimeSettingsOpen] = useState(false)
  const [runtimeSettingsError, setRuntimeSettingsError] = useState('')
  const [runtimeSettingsForm, setRuntimeSettingsForm] = useState<RuntimeSettingsForm>(() => ({
    baseUrl: normalizeBaseUrl(localStorage.getItem('aidm:baseUrl') ?? DEFAULT_BASE_URL),
    authToken: localStorage.getItem('aidm:authToken') ?? '',
  }))
  const [createPlayerPending, setCreatePlayerPending] = useState(false)
  const [createMapPending, setCreateMapPending] = useState(false)
  const [createCampaignForm, setCreateCampaignForm] = useState<CreateCampaignForm>({
    title: '',
    description: '',
    worldName: '',
  })
  const [socketReconnectKey, setSocketReconnectKey] = useState(0)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [loadingCampaignId, setLoadingCampaignId] = useState<number | null>(null)
  const [sessionLoading, setSessionLoading] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const rootRef = useRef<HTMLDivElement | null>(null)
  const accountMenuRef = useRef<HTMLDivElement | null>(null)
  const sessionMenuRef = useRef<HTMLDivElement | null>(null)
  const turnFeedRef = useRef<HTMLElement | null>(null)
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null)
  const ttsAudioUrlRef = useRef<string | null>(null)
  const lastSpokenDmEntryRef = useRef<string | null>(null)
  const speakDmEntryRef = useRef<((entry: TimelineEntry) => void) | null>(null)
  const queueTtsNarrationRef = useRef<((text: string) => void) | null>(null)
  const ttsEnabledRef = useRef(ttsEnabled)
  const lastSpokenTurnIdRef = useRef<number | null>(null)
  const socketRef = useRef<Socket | null>(null)
  const workspaceRequestRef = useRef(0)
  const sessionRequestRef = useRef(0)
  const playerRequestRef = useRef(0)
  const ttsQueueRef = useRef<TtsQueueItem[]>([])
  const ttsCurrentItemRef = useRef<TtsQueueItem | null>(null)
  const ttsPlayingRef = useRef(false)
  const spokenTextLengthRef = useRef(0)
  const speakableStreamingTextRef = useRef('')
  const ttsPartialFlushTimerRef = useRef<number | null>(null)
  const ttsLoopIdRef = useRef(0)
  const lastSpokenTextRef = useRef<string | null>(null)
  const spokenTtsKeysRef = useRef<Map<string, number>>(new Map())

  const auth = authToken.trim()
  const selectedPlayer = useMemo(
    () => players.find((player) => player.player_id === selectedPlayerId) ?? null,
    [players, selectedPlayerId],
  )

  const timeline = useMemo(() => {
    const entries = logEntries.map(timelineFromLog).concat(optimisticEntries)
    if (streamingTurn) {
      entries.push({
        id: `stream-${streamingTurn.turnId}`,
        role: 'dm',
        speaker: 'DM',
        text: streamingTurn.text || '...',
        timestamp: null,
        metadata: {
          turn_id: streamingTurn.turnId,
          requires_roll: streamingTurn.requiresRoll,
          ...streamingTurn.rulesHint,
        },
        streaming: true,
      })
    }
    return entries
  }, [logEntries, optimisticEntries, streamingTurn])

  const activeSession =
    sessions.find((session) => session.session_id === selectedSessionId) ?? null
  const activeSessionName = activeSession
    ? sessionDisplayName(activeSession, campaign?.world_id ?? selectedCampaignId)
    : 'No session selected'
  const latestDmEntry =
    [...timeline].reverse().find((entry) => entry.role === 'dm') ?? null
  const currentResponseEntry =
    timeline.find((entry) => entry.streaming) ?? latestDmEntry
  const turnRows = timeline.filter((entry) => entry.id !== currentResponseEntry?.id)
  const speakableDmEntry =
    currentResponseEntry?.role === 'dm' && !currentResponseEntry.streaming
      ? currentResponseEntry
      : null
  const welcomeText = activeSession
    ? `Welcome to ${activeSessionName}. Choose an opening move and the DM will begin the scene.`
    : 'Start or select a session to begin play.'
  const latestDmText =
    currentResponseEntry?.text ||
    sessionState?.rolling_summary ||
    welcomeText

  const ttsDedupeScope = selectedSessionId ? `session:${selectedSessionId}` : 'session:none'
  const scopedTtsKey = useCallback(
    (key: string) => `${ttsDedupeScope}:${key}`,
    [ttsDedupeScope],
  )
  const rememberSpokenTts = useCallback(
    (text: string, turnId: number | null) => {
      const now = Date.now()
      const keys = ttsDedupeKeysForText(text, turnId)
      keys.forEach((key) => spokenTtsKeysRef.current.set(scopedTtsKey(key), now))
      for (const [storedKey, spokenAt] of spokenTtsKeysRef.current) {
        if (storedKey.includes(':text:') && now - spokenAt > TTS_RECENT_TEXT_DEDUPE_MS) {
          spokenTtsKeysRef.current.delete(storedKey)
        }
      }
      if (spokenTtsKeysRef.current.size > 160) {
        spokenTtsKeysRef.current = new Map([...spokenTtsKeysRef.current].slice(-80))
      }
    },
    [scopedTtsKey],
  )
  const wasTtsAlreadySpoken = useCallback(
    (entry: TimelineEntry) => {
      const now = Date.now()
      const entryTurnId = metadataTurnId(entry.metadata)
      return ttsDedupeKeysForEntry(entry).some((key) => {
        if (entryTurnId !== null && key.startsWith('text:')) return false
        const spokenAt = spokenTtsKeysRef.current.get(scopedTtsKey(key))
        if (spokenAt === undefined) return false
        if (key.startsWith('turn:')) return true
        return now - spokenAt <= TTS_RECENT_TEXT_DEDUPE_MS
      })
    },
    [scopedTtsKey],
  )

  const campaignTitle = campaign?.title ?? 'No campaign selected'
  const activeSessionTitle = activeSession
    ? sessionDisplayName(activeSession, campaign?.world_id ?? selectedCampaignId)
    : selectedCampaignId
      ? 'No session selected'
      : 'Select a campaign'
  const effectiveTtsStatus: TtsPlaybackStatus = ttsEnabled ? ttsStatus : 'off'
  const ttsStatusLabel =
    effectiveTtsStatus === 'off'
      ? 'Off'
      : effectiveTtsStatus === 'ready'
        ? 'Ready'
        : effectiveTtsStatus === 'queued'
          ? `${ttsQueueCount} queued`
          : effectiveTtsStatus === 'requesting'
            ? 'Requesting'
            : effectiveTtsStatus === 'speaking'
              ? 'Speaking'
              : 'Failed'
  const canStopTts = ['queued', 'requesting', 'speaking'].includes(effectiveTtsStatus)
  const realtimeLabel =
    socketStatus === 'joined'
      ? 'Joined'
      : socketStatus === 'connecting' || socketStatus === 'joining'
        ? 'Connecting'
        : socketStatus === 'error'
          ? 'Error'
          : socketStatus === 'offline'
            ? 'Offline'
            : health?.status === 'ok'
              ? 'Standby'
              : 'Offline'
  const realtimeTone: 'good' | 'neutral' | 'warn' =
    realtimeLabel === 'Joined'
      ? 'good'
      : realtimeLabel === 'Error' || realtimeLabel === 'Offline'
        ? 'warn'
        : 'neutral'

  const loadSessionData = useCallback(
    async (sessionId: number) => {
      const requestId = ++sessionRequestRef.current
      setSessionLoading(true)
      try {
        const [logData, stateData] = await Promise.all([
          apiFetch<SessionLogResponse>(
            baseUrl,
            `/api/sessions/${sessionId}/log?limit=200`,
            auth,
          ),
          apiFetch<SessionState>(baseUrl, `/api/sessions/${sessionId}/state`, auth),
        ])
        if (sessionRequestRef.current !== requestId) return
        setLogEntries(logData.entries)
        setSessionState(stateData)
        setCampaignSessionMeta((current) => {
          const existing = current[stateData.campaign_id]
          return {
            ...current,
            [stateData.campaign_id]: {
              count: existing?.count ?? sessions.length,
              latestSessionId: existing?.latestSessionId ?? sessionId,
              updatedAt: latestTimestamp([
                existing?.updatedAt,
                stateData.updated_at,
                sessions.find((session) => session.session_id === sessionId)?.created_at,
              ]),
            },
          }
        })
      } finally {
        if (sessionRequestRef.current === requestId) {
          setSessionLoading(false)
        }
      }
    },
    [auth, baseUrl, sessions],
  )

  const refreshRoot = useCallback(async () => {
    try {
      const [healthData, campaignData, metricData, llmData] = await Promise.all([
        apiFetch<Health>(baseUrl, '/api/health', auth),
        apiFetch<Campaign[]>(baseUrl, '/api/campaigns', auth),
        apiFetch<BetaSummary>(baseUrl, '/api/beta/summary', auth),
        apiFetch<LlmRuntimeConfig>(baseUrl, '/api/llm/config', auth),
      ])
      setHealth(healthData)
      setCampaigns(campaignData)
      setMetrics(metricData)
      setLlmConfig(llmData)
      setCampaignSessionMeta(
        Object.fromEntries(
          campaignData.map((item) => [item.campaign_id, sessionMetaFromCampaign(item)]),
        ),
      )
      void apiFetch<TtsRuntimeConfig>(baseUrl, '/api/tts/config', auth)
        .then(setTtsConfig)
        .catch(() => {
          setTtsConfig({ provider: 'deepgram', configured: false, model: 'aura-2-draco-en' })
        })
      setSelectedCampaignId((current) => {
        if (campaignData.some((item) => item.campaign_id === current)) {
          return current
        }
        return campaignData[0]?.campaign_id ?? null
      })
    } catch (error) {
      setHealth(null)
      setErrors((current) => [
        `Connection failed: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    }
  }, [auth, baseUrl])

  const refreshCampaignWorkspace = useCallback(
    async (campaignId: number) => {
      const requestId = ++workspaceRequestRef.current
      setWorkspaceLoading(true)
      setLoadingCampaignId(campaignId)
      try {
        const workspace = await apiFetch<CampaignWorkspace>(
          baseUrl,
          `/api/campaigns/${campaignId}/workspace`,
          auth,
        )
        if (workspaceRequestRef.current !== requestId) return
        const campaignData = workspace.campaign
        const sessionData = workspace.sessions
        const playerData = workspace.players
        const mapData = workspace.maps
        const segmentData = workspace.segments
        setCampaign(campaignData)
        setSessions(sessionData)
        setCampaignSessionMeta((current) => ({
          ...current,
          [campaignId]: {
            count: workspace.summary.session_count,
            updatedAt: workspace.summary.latest_activity_at ?? campaignData.created_at,
            latestSessionId: workspace.summary.latest_session_id,
          },
        }))
        setPlayers(playerData)
        setMaps(mapData)
        setSegments(segmentData)
        setSelectedSessionId((current) => {
          if (sessionData.some((item) => item.session_id === current)) {
            return current
          }
          return sessionData[0]?.session_id ?? null
        })
        setSelectedPlayerId((current) => {
          if (playerData.some((item) => item.player_id === current)) {
            return current
          }
          return playerData[0]?.player_id ?? null
        })
        setOptimisticEntries([])
        setStreamingTurn(null)
        setSendPending(false)
      } catch (error) {
        if (workspaceRequestRef.current === requestId) {
          setErrors((current) => [
            `Workspace load failed: ${error instanceof Error ? error.message : String(error)}`,
            ...current.slice(0, 3),
          ])
        }
      } finally {
        if (workspaceRequestRef.current === requestId) {
          setWorkspaceLoading(false)
          setLoadingCampaignId(null)
        }
      }
    },
    [auth, baseUrl],
  )

  const startSession = async () => {
    if (!selectedCampaignId) return
    try {
      const result = await apiFetch<{ session_id: number }>(
        baseUrl,
        '/api/sessions/start',
        auth,
        {
          method: 'POST',
          body: JSON.stringify({ campaign_id: selectedCampaignId }),
        },
      )
      setSelectedSessionId(result.session_id)
      await refreshCampaignWorkspace(selectedCampaignId)
    } catch (error) {
      setErrors((current) => [
        `Could not start session: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    }
  }

  const createDefaultPlayer = async () => {
    if (!selectedCampaignId) return
    setCreatePlayerPending(true)
    try {
      const result = await apiFetch<{ player_id: number }>(
        baseUrl,
        `/api/players/campaigns/${selectedCampaignId}/players`,
        auth,
        {
          method: 'POST',
          body: JSON.stringify({
            name: 'Local Player',
            character_name: 'New Adventurer',
            race: '',
            char_class: '',
            level: 1,
          }),
        },
      )
      await refreshCampaignWorkspace(selectedCampaignId)
      setSelectedPlayerId(result.player_id)
      setInspectorTab('party')
    } catch (error) {
      setErrors((current) => [
        `Could not create player: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    } finally {
      setCreatePlayerPending(false)
    }
  }

  const createDefaultMap = async () => {
    if (!selectedCampaignId || !campaign) return
    setCreateMapPending(true)
    try {
      await apiFetch<{ map_id: number }>(baseUrl, '/api/maps', auth, {
        method: 'POST',
        body: JSON.stringify({
          campaign_id: selectedCampaignId,
          world_id: campaign.world_id,
          title: `${campaign.title} Map`,
          description: campaign.location || 'Campaign map notes.',
          map_data: {},
        }),
      })
      await refreshCampaignWorkspace(selectedCampaignId)
      setInspectorTab('map')
    } catch (error) {
      setErrors((current) => [
        `Could not create map: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    } finally {
      setCreateMapPending(false)
    }
  }

  const submitAction = (overrideMessage?: string) => {
    if (
      !socketRef.current ||
      !selectedSessionId ||
      !selectedCampaignId ||
      !campaign ||
      !selectedPlayerId
    ) {
      setErrors((current) => [
        'Choose a campaign, session, and player before sending.',
        ...current.slice(0, 3),
      ])
      return
    }
    const message = (overrideMessage ?? actionText).trim()
    if (!message) return

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
        metadata: {},
      },
    ])
    socketRef.current.emit('send_message', {
      session_id: selectedSessionId,
      campaign_id: selectedCampaignId,
      world_id: campaign.world_id,
      player_id: selectedPlayerId,
      message,
    })
    setActionText('')
  }

  const refreshCurrentWorkspace = useCallback(async () => {
    await refreshRoot()
    if (selectedCampaignId) {
      await refreshCampaignWorkspace(selectedCampaignId)
    }
    if (selectedSessionId) {
      await loadSessionData(selectedSessionId)
    }
  }, [
    loadSessionData,
    refreshCampaignWorkspace,
    refreshRoot,
    selectedCampaignId,
    selectedSessionId,
  ])

  const updateJumpToLatestVisibility = useCallback(() => {
    const feed = turnFeedRef.current
    if (!feed) return
    const distanceFromBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight
    setShowJumpToLatest(distanceFromBottom > 96)
  }, [])

  const scrollTurnFeedToLatest = useCallback(() => {
    const feed = turnFeedRef.current
    if (!feed) return
    feed.scrollTo({ top: feed.scrollHeight, behavior: 'smooth' })
    setShowJumpToLatest(false)
  }, [])

  useEffect(() => {
    setShowJumpToLatest(false)
  }, [mainTab, selectedSessionId])

  useEffect(() => {
    if (mainTab !== 'turns' || showJumpToLatest) return
    const frame = window.requestAnimationFrame(() => {
      const feed = turnFeedRef.current
      if (feed) {
        feed.scrollTop = feed.scrollHeight
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [latestDmText, mainTab, showJumpToLatest, timeline.length])

  const downloadSessionJson = async () => {
    const warnings: string[] = []
    const [turnEventsResult, canonResult] = await Promise.allSettled([
      selectedSessionId
        ? apiFetch<SessionEventsResponse>(
            baseUrl,
            `/api/sessions/${selectedSessionId}/events?limit=1000`,
            auth,
          )
        : Promise.resolve<SessionEventsResponse | null>(null),
      selectedCampaignId
        ? apiFetch<CampaignCanon>(baseUrl, `/api/campaigns/${selectedCampaignId}/canon`, auth)
        : Promise.resolve<CampaignCanon | null>(null),
    ])

    const turnEvents =
      turnEventsResult.status === 'fulfilled' ? turnEventsResult.value : null
    const canon = canonResult.status === 'fulfilled' ? canonResult.value : null
    if (turnEventsResult.status === 'rejected') {
      warnings.push(`turn events unavailable: ${turnEventsResult.reason}`)
    }
    if (canonResult.status === 'rejected') {
      warnings.push(`canon unavailable: ${canonResult.reason}`)
    }

    const payload = {
      exportedAt: new Date().toISOString(),
      selectedIds: {
        campaignId: selectedCampaignId,
        sessionId: selectedSessionId,
        playerId: selectedPlayerId,
      },
      campaign,
      selectedSession: activeSession,
      players,
      selectedPlayer: playerDetail ?? selectedPlayer,
      sessionState,
      logEntries,
      turnEvents: turnEvents?.events ?? [],
      canon,
      maps,
      segments,
      metrics,
      warnings,
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `aidm-session-${selectedSessionId ?? 'export'}.json`
    link.click()
    URL.revokeObjectURL(url)
    if (warnings.length) {
      setErrors((current) => [
        `Export completed with missing live data: ${warnings.join('; ')}`,
        ...current.slice(0, 3),
      ])
    }
  }

  const shareSession = () => {
    const params = new URLSearchParams()
    if (selectedCampaignId) params.set('campaign', String(selectedCampaignId))
    if (selectedSessionId) params.set('session', String(selectedSessionId))
    const shareUrl = `${window.location.origin}${window.location.pathname}?${params.toString()}`
    if (!navigator.clipboard) {
      setErrors((current) => ['Clipboard unavailable for sharing.', ...current.slice(0, 2)])
      return
    }
    void navigator.clipboard.writeText(shareUrl).then(
      () => {
        setErrors((current) => ['Session link copied.', ...current.slice(0, 2)])
      },
      () => {
        setErrors((current) => ['Clipboard unavailable for sharing.', ...current.slice(0, 2)])
      },
    )
  }

  const stopTtsAudio = useCallback(() => {
    ttsLoopIdRef.current += 1

    if (ttsPartialFlushTimerRef.current !== null) {
      window.clearTimeout(ttsPartialFlushTimerRef.current)
      ttsPartialFlushTimerRef.current = null
    }

    ttsCurrentItemRef.current?.controller.abort()
    ttsCurrentItemRef.current?.cleanup?.()
    ttsCurrentItemRef.current = null

    for (const item of ttsQueueRef.current) {
      item.controller.abort()
      item.cleanup?.()
    }
    ttsQueueRef.current = []
    setTtsQueueCount(0)

    ttsAudioRef.current?.pause()
    ttsAudioRef.current = null
    ttsPlayingRef.current = false
    spokenTextLengthRef.current = 0
    speakableStreamingTextRef.current = ''
    if (ttsAudioUrlRef.current) {
      URL.revokeObjectURL(ttsAudioUrlRef.current)
      ttsAudioUrlRef.current = null
    }
    setTtsSpeaking(false)
    setTtsStatus(ttsEnabledRef.current ? 'ready' : 'off')
  }, [])

  const toggleTts = () => {
    if (ttsEnabled) {
      stopTtsAudio()
      setTtsEnabled(false)
      setTtsStatus('off')
      return
    }
    if (ttsConfig && !ttsConfig.configured) {
      setErrors((current) => [
        'Deepgram TTS is not configured on the backend.',
        ...current.slice(0, 3),
      ])
      return
    }
    setTtsEnabled(true)
    setTtsStatus('ready')
  }

  const processTtsQueue = useCallback(async () => {
    if (ttsPlayingRef.current || ttsQueueRef.current.length === 0 || !ttsEnabled) return
    ttsPlayingRef.current = true

    ttsLoopIdRef.current += 1
    const currentLoopId = ttsLoopIdRef.current

    while (ttsQueueRef.current.length > 0) {
      if (!ttsEnabled || ttsLoopIdRef.current !== currentLoopId) break

      const item = ttsQueueRef.current.shift()
      if (!item) continue
      setTtsQueueCount(ttsQueueRef.current.length)
      ttsCurrentItemRef.current = item

      setTtsSpeaking(false)
      setTtsStatus('requesting')
      let audioUrl: string | null = null

      try {
        audioUrl = await item.audioUrlPromise

        if (ttsLoopIdRef.current !== currentLoopId || item.controller.signal.aborted) {
          if (audioUrl) URL.revokeObjectURL(audioUrl)
          break
        }

        if (!audioUrl) continue

        const audio = new Audio(audioUrl)
        audio.preload = 'auto'
        ttsAudioRef.current = audio
        ttsAudioUrlRef.current = audioUrl
        setTtsSpeaking(true)
        setTtsStatus('speaking')

        await new Promise<void>((resolve, reject) => {
          audio.onended = () => resolve()
          audio.onerror = (e) => reject(e)
          audio.onpause = () => resolve()
          audio.play().catch(reject)
        })

        await item.streamDone?.catch(() => undefined)
        if (ttsAudioUrlRef.current === audioUrl) {
          URL.revokeObjectURL(audioUrl)
          ttsAudioUrlRef.current = null
        }
      } catch (error) {
        if (!item.controller.signal.aborted && ttsLoopIdRef.current === currentLoopId) {
          setTtsStatus('failed')
          setTtsSpeaking(false)
          setErrors((current) => [
            `TTS playback failed: ${ttsPlaybackErrorMessage(error)}`,
            ...current.slice(0, 3),
          ])
        }
        if (audioUrl && ttsAudioUrlRef.current === audioUrl) {
          URL.revokeObjectURL(audioUrl)
          ttsAudioUrlRef.current = null
        }
      } finally {
        item.cleanup?.()
        if (ttsCurrentItemRef.current === item) {
          ttsCurrentItemRef.current = null
        }
      }
    }

    if (ttsLoopIdRef.current === currentLoopId) {
      setTtsSpeaking(false)
      ttsPlayingRef.current = false
      ttsAudioRef.current = null
      setTtsQueueCount(ttsQueueRef.current.length)
      if (ttsQueueRef.current.length === 0 && ttsEnabledRef.current) {
        setTtsStatus('ready')
      }
    }
  }, [ttsEnabled])

  const queueTtsText = useCallback(
    (text: string) => {
      if (!ttsEnabled) return
      let cleanText = text.replace(/<thought>[\s\S]*?(?:<\/thought>|$)/gi, '')
      cleanText = stripMarkdown(cleanText).replace(/\s+/g, ' ').trim()
      if (!cleanText) return

      const controller = new AbortController()

      const headers = new Headers({ 'Content-Type': 'application/json' })
      if (auth) {
        headers.set('Authorization', `Bearer ${auth}`)
      }

      const requestAudio = () =>
        fetch(`${normalizeBaseUrl(baseUrl)}/api/tts/speak`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ text: cleanText }),
          signal: controller.signal,
        })

      const reportTtsError = (message: string) => {
        setTtsStatus('failed')
        setErrors((current) => [`TTS failed: ${message}`, ...current.slice(0, 3)])
      }

      const streamedSource = createStreamingTtsSource(requestAudio, controller, reportTtsError)
      const promise =
        streamedSource?.audioUrl
          ? Promise.resolve(streamedSource.audioUrl)
          : requestAudio()
              .then(async (response) => {
                if (!response.ok) {
                  reportTtsError(await ttsErrorMessage(response))
                  return null
                }
                const blob = await response.blob()
                if (controller.signal.aborted) return null
                return URL.createObjectURL(blob)
              })
              .catch((error) => {
                if (error.name !== 'AbortError') {
                  reportTtsError(error instanceof Error ? error.message : String(error))
                }
                return null
              })

      ttsQueueRef.current.push({
        text: cleanText,
        audioUrlPromise: promise,
        controller,
        cleanup: streamedSource?.cleanup,
        streamDone: streamedSource?.streamDone,
      })
      setTtsQueueCount(ttsQueueRef.current.length)
      setTtsStatus('queued')
      void processTtsQueue()
    },
    [auth, baseUrl, processTtsQueue, ttsEnabled],
  )

  const queueTtsNarration = useCallback(
    (text: string) => {
      let remaining = text.replace(/<thought>[\s\S]*?(?:<\/thought>|$)/gi, '').trim()
      while (remaining.trim()) {
        const flushLength = ttsFlushLength(remaining, true) || remaining.length
        queueTtsText(remaining.slice(0, flushLength))
        remaining = remaining.slice(flushLength)
      }
    },
    [queueTtsText],
  )

  const speakDmEntry = useCallback(
    async (entry: TimelineEntry) => {
      if (!ttsEnabled) return
      stopTtsAudio()
      queueTtsNarration(entry.text)
    },
    [queueTtsNarration, stopTtsAudio, ttsEnabled],
  )

  const flushStreamingTtsChunks = useCallback(
    (forcePartial = false) => {
      let pending = speakableStreamingTextRef.current.slice(spokenTextLengthRef.current)
      while (pending.trim()) {
        const flushLength = ttsFlushLength(pending, forcePartial)
        if (flushLength <= 0) break

        const chunk = pending.slice(0, flushLength)
        spokenTextLengthRef.current += flushLength
        queueTtsText(chunk)
        pending = speakableStreamingTextRef.current.slice(spokenTextLengthRef.current)
        forcePartial = false
      }
    },
    [queueTtsText],
  )

  const toggleFullscreen = async () => {
    try {
      if (fullscreenFallback) {
        setFullscreenFallback(false)
        return
      }
      if (document.fullscreenElement) {
        await document.exitFullscreen()
        return
      }
      await rootRef.current?.requestFullscreen()
    } catch {
      setFullscreenFallback(true)
      setErrors((current) => [
        'Native fullscreen was blocked by this browser, so app fullscreen mode is active.',
        ...current.slice(0, 3),
      ])
    }
  }

  const openCreateCampaignDialog = () => {
    setCreateCampaignForm({
      title: '',
      description: '',
      worldName: '',
    })
    setCreateCampaignError('')
    setCreateCampaignOpen(true)
  }

  const closeCreateCampaignDialog = () => {
    if (createCampaignPending) return
    setCreateCampaignOpen(false)
    setCreateCampaignError('')
  }

  const openRuntimeSettingsDialog = () => {
    setRuntimeSettingsForm({ baseUrl, authToken })
    setRuntimeSettingsError('')
    setAccountMenuOpen(false)
    setRuntimeSettingsOpen(true)
  }

  const closeRuntimeSettingsDialog = () => {
    setRuntimeSettingsOpen(false)
    setRuntimeSettingsError('')
  }

  const submitRuntimeSettings = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextBaseUrl = normalizeBaseUrl(runtimeSettingsForm.baseUrl)
    const nextAuthToken = runtimeSettingsForm.authToken.trim()

    if (!nextBaseUrl) {
      setRuntimeSettingsError('Backend URL is required.')
      return
    }

    try {
      const url = new URL(nextBaseUrl)
      if (!['http:', 'https:'].includes(url.protocol)) {
        setRuntimeSettingsError('Backend URL must start with http:// or https://.')
        return
      }
    } catch {
      setRuntimeSettingsError('Enter a valid backend URL.')
      return
    }

    localStorage.setItem('aidm:baseUrl', nextBaseUrl)
    if (nextAuthToken) {
      localStorage.setItem('aidm:authToken', nextAuthToken)
    } else {
      localStorage.removeItem('aidm:authToken')
    }

    setBaseUrl(nextBaseUrl)
    setAuthToken(nextAuthToken)
    setHealth(null)
    setLlmConfig(null)
    setTtsConfig(null)
    setMetrics(null)
    setSocketReconnectKey((current) => current + 1)
    setRuntimeSettingsOpen(false)
    setRuntimeSettingsError('')
  }

  const createWorldForCampaign = async (title: string, description: string) => {
    const worldName = createCampaignForm.worldName.trim() || `${title} World`
    const world = await apiFetch<Pick<World, 'world_id'>>(baseUrl, '/api/worlds', auth, {
      method: 'POST',
      body: JSON.stringify({
        name: worldName,
        description: description || `World for ${title}`,
      }),
    })
    return world.world_id
  }

  const submitCreateCampaign = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault()
    const title = createCampaignForm.title.trim()
    const description = createCampaignForm.description.trim()
    if (!title) {
      setCreateCampaignError('Campaign name is required.')
      return
    }

    setCreateCampaignPending(true)
    setCreateCampaignError('')

    try {
      let createdWorld = false
      let worldId: number | null = null
      if (createCampaignForm.worldName.trim() || !campaigns.length) {
        worldId = await createWorldForCampaign(title, description)
        createdWorld = true
      } else {
        worldId = campaign?.world_id ?? campaigns[0]?.world_id ?? null
      }

      const createCampaign = (nextWorldId: number) =>
        apiFetch<{ campaign_id: number }>(baseUrl, '/api/campaigns', auth, {
          method: 'POST',
          body: JSON.stringify({
            title,
            world_id: nextWorldId,
            description,
          }),
        })

      let result: { campaign_id: number }
      if (!worldId) {
        worldId = await createWorldForCampaign(title, description)
        createdWorld = true
      }

      try {
        result = await createCampaign(worldId)
      } catch (error) {
        if (error instanceof ApiClientError && error.status === 404 && !createdWorld) {
          worldId = await createWorldForCampaign(title, description)
          result = await createCampaign(worldId)
        } else {
          throw error
        }
      }

      setCreateCampaignOpen(false)
      setCreateCampaignForm({ title: '', description: '', worldName: '' })
      setSelectedSessionId(null)
      setLogEntries([])
      setSessionState(null)
      setOptimisticEntries([])
      setStreamingTurn(null)
      setMainTab('turns')
      setInspectorTab('party')
      await refreshRoot()
      setSelectedCampaignId(result.campaign_id)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setCreateCampaignError(message)
      setErrors((current) => [`Could not create campaign: ${message}`, ...current.slice(0, 3)])
    } finally {
      setCreateCampaignPending(false)
    }
  }

  const renameSelectedSession = async () => {
    if (!activeSession) return
    const currentName = sessionDisplayName(activeSession, campaign?.world_id ?? selectedCampaignId)
    const nextName = window.prompt('Session name', currentName)
    if (!nextName?.trim() || nextName.trim() === currentName) {
      setSessionMenuOpen(false)
      return
    }
    try {
      const updated = await apiFetch<SessionSummary>(
        baseUrl,
        `/api/sessions/${activeSession.session_id}`,
        auth,
        {
          method: 'PATCH',
          body: JSON.stringify({ name: nextName.trim() }),
        },
      )
      setSessions((current) =>
        current.map((session) => (session.session_id === updated.session_id ? updated : session)),
      )
      setSessionMenuOpen(false)
      if (selectedCampaignId) {
        await refreshCampaignWorkspace(selectedCampaignId)
      }
    } catch (error) {
      setErrors((current) => [
        `Could not rename session: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    }
  }

  const deleteSelectedSession = async () => {
    if (!activeSession || !selectedCampaignId) return
    const label = sessionDisplayName(activeSession, campaign?.world_id ?? selectedCampaignId)
    if (!window.confirm(`Delete ${label}? This removes its log and turn history.`)) {
      setSessionMenuOpen(false)
      return
    }
    try {
      await apiFetch<{ deleted: boolean }>(
        baseUrl,
        `/api/sessions/${activeSession.session_id}`,
        auth,
        { method: 'DELETE' },
      )
      setSessionMenuOpen(false)
      setOptimisticEntries([])
      setStreamingTurn(null)
      setLogEntries([])
      setSessionState(null)
      await refreshCampaignWorkspace(selectedCampaignId)
    } catch (error) {
      setErrors((current) => [
        `Could not delete session: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    }
  }

  const applyComposerMode = (mode: ComposerMode, die = selectedDie) => {
    setComposerMode(mode)
    setActionText((current) =>
      composerTextForMode(mode, current, selectedPlayer?.character_name ?? 'I', die),
    )
  }

  const updateSelectedDie = (die: string) => {
    setSelectedDie(die)
    if (composerMode === 'roll') {
      setActionText((current) =>
        composerTextForMode('roll', current, selectedPlayer?.character_name ?? 'I', die),
      )
    }
  }

  const startDiceRoll = (die = selectedDie) => {
    if (sendPending) {
      setErrors((current) => [
        'Wait for the current DM response before rolling again.',
        ...current.slice(0, 3),
      ])
      return
    }
    if (
      !socketRef.current ||
      !selectedSessionId ||
      !selectedCampaignId ||
      !campaign ||
      !selectedPlayerId
    ) {
      setErrors((current) => [
        'Choose a campaign, session, and player before rolling.',
        ...current.slice(0, 3),
      ])
      return
    }

    const normalizedDie = DICE_OPTIONS.includes(die.toLowerCase()) ? die.toLowerCase() : 'd20'
    const result = rollDie(normalizedDie)
    const message = diceRollMessage(normalizedDie, result)
    setSelectedDie(normalizedDie)
    setComposerMode('roll')
    setActionText(message)
    setDiceRoll({
      die: normalizedDie,
      result,
      rollKey: Date.now(),
      status: 'rolling',
    })
  }

  const completeDiceRoll = () => {
    if (!diceRoll || diceRoll.status !== 'rolling') return
    const { die, result, rollKey } = diceRoll
    const message = diceRollMessage(die, result)
    setDiceRoll((current) =>
      current?.rollKey === rollKey ? { ...current, status: 'sending' } : current,
    )
    submitAction(message)
    window.setTimeout(() => {
      setDiceRoll((current) => (current?.rollKey === rollKey ? null : current))
    }, 450)
  }

  const switchRuntime = useCallback(
    async (provider: string, model: string) => {
      if (!provider || !model) return
      setRuntimePending(true)
      try {
        const nextConfig = await apiFetch<LlmRuntimeConfig>(
          baseUrl,
          '/api/llm/config',
          auth,
          {
            method: 'PATCH',
            body: JSON.stringify({ provider, model, persist: true }),
          },
        )
        setLlmConfig(nextConfig)
        setHealth((current) =>
          current
            ? {
                ...current,
                llm: nextConfig.current,
              }
            : current,
        )
      } catch (error) {
        setErrors((current) => [
          `Runtime switch failed: ${error instanceof Error ? error.message : String(error)}`,
          ...current.slice(0, 3),
        ])
      } finally {
        setRuntimePending(false)
      }
    },
    [auth, baseUrl],
  )

  useEffect(() => {
    refreshRoot()
  }, [refreshRoot])

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    localStorage.setItem('aidm:theme', theme)
  }, [theme])

  useEffect(() => {
    localStorage.setItem('aidm:ttsEnabled', String(ttsEnabled))
  }, [ttsEnabled])

  useEffect(() => {
    if (!ttsEnabled) {
      stopTtsAudio()
    }
  }, [stopTtsAudio, ttsEnabled])

  useEffect(() => {
    return () => stopTtsAudio()
  }, [stopTtsAudio])

  // Keep ref in sync so the socket handler can call the latest speakDmEntry
  // without adding it as a socket-effect dependency (which would reconnect).
  useEffect(() => {
    ttsEnabledRef.current = ttsEnabled
    speakDmEntryRef.current = ttsEnabled ? speakDmEntry : null
    queueTtsNarrationRef.current = ttsEnabled ? queueTtsNarration : null
  }, [queueTtsNarration, speakDmEntry, ttsEnabled])

  // Trigger TTS for DM entries that appear from log refresh / page reload.
  // The streaming→TTS path is handled directly in the dm_response_end handler.
  useEffect(() => {
    if (!ttsEnabled || !speakableDmEntry || sendPending || streamingTurn) return
    if (lastSpokenDmEntryRef.current === speakableDmEntry.id) return
    const entryTurnId = metadataTurnId(speakableDmEntry.metadata)
    if (wasTtsAlreadySpoken(speakableDmEntry)) {
      lastSpokenDmEntryRef.current = speakableDmEntry.id
      lastSpokenTextRef.current = speakableDmEntry.text
      if (entryTurnId !== null) {
        lastSpokenTurnIdRef.current = entryTurnId
      }
      return
    }
    // Skip if this entry's turn was already spoken via the streaming path.
    if (
      entryTurnId !== null &&
      lastSpokenTurnIdRef.current !== null &&
      entryTurnId === lastSpokenTurnIdRef.current
    ) {
      lastSpokenDmEntryRef.current = speakableDmEntry.id
      lastSpokenTextRef.current = speakableDmEntry.text
      rememberSpokenTts(speakableDmEntry.text, entryTurnId)
      return
    }

    const cleanSpeakableText = cleanNarrationText(speakableDmEntry.text)
    const cleanLastSpokenText = lastSpokenTextRef.current ? cleanNarrationText(lastSpokenTextRef.current) : null
    if (
      entryTurnId === null &&
      lastSpokenTurnIdRef.current !== null &&
      cleanSpeakableText === cleanLastSpokenText
    ) {
      lastSpokenDmEntryRef.current = speakableDmEntry.id
      lastSpokenTextRef.current = speakableDmEntry.text
      rememberSpokenTts(speakableDmEntry.text, entryTurnId)
      return
    }

    lastSpokenDmEntryRef.current = speakableDmEntry.id
    lastSpokenTextRef.current = speakableDmEntry.text
    rememberSpokenTts(speakableDmEntry.text, entryTurnId)
    void speakDmEntry(speakableDmEntry)
  }, [
    rememberSpokenTts,
    sendPending,
    speakDmEntry,
    speakableDmEntry,
    streamingTurn,
    ttsEnabled,
    wasTtsAlreadySpoken,
  ])

  const speakableStreamingText = useMemo(() => {
    if (!streamingTurn?.text) return ''
    return streamingTurn.text.replace(/<thought>[\s\S]*?(?:<\/thought>|$)/gi, '')
  }, [streamingTurn?.text])

  // Process streaming text for TTS in chunks as it appears.
  useEffect(() => {
    speakableStreamingTextRef.current = speakableStreamingText
    if (ttsPartialFlushTimerRef.current !== null) {
      window.clearTimeout(ttsPartialFlushTimerRef.current)
      ttsPartialFlushTimerRef.current = null
    }
    if (!speakableStreamingText) return

    flushStreamingTtsChunks(false)

    const remaining = speakableStreamingTextRef.current.slice(spokenTextLengthRef.current).trim()
    if (remaining.length >= TTS_MIN_PARTIAL_FLUSH_CHARS) {
      ttsPartialFlushTimerRef.current = window.setTimeout(() => {
        ttsPartialFlushTimerRef.current = null
        flushStreamingTtsChunks(true)
      }, TTS_PARTIAL_FLUSH_DELAY_MS)
    }
  }, [flushStreamingTtsChunks, speakableStreamingText])

  useEffect(() => {
    const updateFullscreenState = () => {
      const active = Boolean(document.fullscreenElement)
      setIsFullscreen(active)
      if (active) {
        setFullscreenFallback(false)
      }
    }
    updateFullscreenState()
    document.addEventListener('fullscreenchange', updateFullscreenState)
    return () => {
      document.removeEventListener('fullscreenchange', updateFullscreenState)
    }
  }, [])

  useEffect(() => {
    if (!fullscreenFallback) return undefined
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setFullscreenFallback(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreenFallback])

  useEffect(() => {
    if (!accountMenuOpen && !sessionMenuOpen) return undefined

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (accountMenuOpen && !accountMenuRef.current?.contains(target)) {
        setAccountMenuOpen(false)
      }
      if (sessionMenuOpen && !sessionMenuRef.current?.contains(target)) {
        setSessionMenuOpen(false)
      }
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAccountMenuOpen(false)
        setSessionMenuOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [accountMenuOpen, sessionMenuOpen])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (selectedCampaignId) {
      params.set('campaign', String(selectedCampaignId))
      localStorage.setItem('aidm:selectedCampaignId', String(selectedCampaignId))
    } else {
      params.delete('campaign')
      localStorage.removeItem('aidm:selectedCampaignId')
    }
    if (selectedSessionId) {
      params.set('session', String(selectedSessionId))
      localStorage.setItem('aidm:selectedSessionId', String(selectedSessionId))
    } else {
      params.delete('session')
      localStorage.removeItem('aidm:selectedSessionId')
    }
    if (selectedPlayerId) {
      params.set('player', String(selectedPlayerId))
      localStorage.setItem('aidm:selectedPlayerId', String(selectedPlayerId))
    } else {
      params.delete('player')
      localStorage.removeItem('aidm:selectedPlayerId')
    }
    const query = params.toString()
    const nextUrl = `${window.location.pathname}${query ? `?${query}` : ''}`
    window.history.replaceState(null, '', nextUrl)
  }, [selectedCampaignId, selectedPlayerId, selectedSessionId])

  useEffect(() => {
    if (selectedCampaignId) {
      refreshCampaignWorkspace(selectedCampaignId)
    }
  }, [refreshCampaignWorkspace, selectedCampaignId])

  useEffect(() => {
    if (!selectedSessionId) {
      sessionRequestRef.current += 1
      setLogEntries([])
      setSessionState(null)
      setSessionLoading(false)
      return
    }
    loadSessionData(selectedSessionId).catch((error: unknown) => {
      setErrors((current) => [
        `Session refresh failed: ${error instanceof Error ? error.message : String(error)}`,
        ...current.slice(0, 3),
      ])
    })
  }, [loadSessionData, selectedSessionId])

  useEffect(() => {
    if (!selectedPlayerId) {
      playerRequestRef.current += 1
      setPlayerDetail(null)
      return
    }
    const requestId = ++playerRequestRef.current
    apiFetch<PlayerDetail>(baseUrl, `/api/players/${selectedPlayerId}`, auth)
      .then((detail) => {
        if (playerRequestRef.current === requestId) {
          setPlayerDetail(detail)
        }
      })
      .catch((error: unknown) => {
        if (playerRequestRef.current === requestId) {
          setPlayerDetail(null)
          setErrors((current) => [
            `Player load failed: ${error instanceof Error ? error.message : String(error)}`,
            ...current.slice(0, 3),
          ])
        }
      })
  }, [auth, baseUrl, selectedPlayerId])

  useEffect(() => {
    if (!selectedSessionId || !selectedPlayerId || !selectedCampaignId) {
      socketRef.current?.disconnect()
      socketRef.current = null
      setSocketStatus('idle')
      return
    }

    const socket = io(baseUrl, {
      auth: auth ? { token: auth } : undefined,
      transports: ['polling'],
      upgrade: false,
    })
    socketRef.current = socket
    setSocketStatus('connecting')

    socket.on('connect', () => {
      setSocketStatus('joining')
      socket.emit('join_session', {
        session_id: selectedSessionId,
        player_id: selectedPlayerId,
      })
    })

    socket.on('connect_error', (error) => {
      setSocketStatus('error')
      setErrors((current) => [
        `Socket connection failed: ${error.message}`,
        ...current.slice(0, 3),
      ])
    })

    socket.on('active_players', () => {
      setSocketStatus('joined')
    })

    socket.on(
      'dm_response_start',
      (payload: {
        turn_id: number
        requires_roll?: boolean
        rules_hint?: RulesHint
      }) => {
        stopTtsAudio()
        setSendPending(true)
        spokenTextLengthRef.current = 0
        setStreamingTurn({
          turnId: payload.turn_id,
          text: '',
          requiresRoll: Boolean(payload.requires_roll),
          rulesHint: payload.rules_hint ?? {},
        })
      },
    )

    socket.on(
      'dm_chunk',
      (payload: {
        turn_id: number
        chunk?: string
        requires_roll?: boolean
        rules_hint?: RulesHint
      }) => {
        setStreamingTurn((current) => {
          if (!current || current.turnId !== payload.turn_id) {
            return {
              turnId: payload.turn_id,
              text: payload.chunk ?? '',
              requiresRoll: Boolean(payload.requires_roll),
              rulesHint: payload.rules_hint ?? {},
            }
          }
          return {
            ...current,
            text: `${current.text}${payload.chunk ?? ''}`,
            requiresRoll: Boolean(payload.requires_roll),
            rulesHint: payload.rules_hint ?? current.rulesHint,
          }
        })
      },
    )

    socket.on('dm_response_end', () => {
      setSendPending(false)
      // Flush the remaining text to TTS queue
      setStreamingTurn((current) => {
        if (current) {
          const syntheticEntry: TimelineEntry = {
            id: `stream-${current.turnId}`,
            role: 'dm',
            speaker: 'DM',
            text: current.text,
            timestamp: null,
            metadata: {
              turn_id: current.turnId,
              requires_roll: current.requiresRoll,
              ...current.rulesHint,
            },
            streaming: false,
          }
          setOptimisticEntries((opt) => [...opt, syntheticEntry])

          if (current.text) {
            const cleanText = current.text.replace(/<thought>[\s\S]*?(?:<\/thought>|$)/gi, '')
            const remaining = cleanText.slice(spokenTextLengthRef.current).trim()
            if (remaining && ttsEnabledRef.current) {
              queueTtsNarrationRef.current?.(remaining)
            }
            lastSpokenDmEntryRef.current = syntheticEntry.id
            lastSpokenTurnIdRef.current = current.turnId
            lastSpokenTextRef.current = current.text
            rememberSpokenTts(current.text, current.turnId)
          }
        }
        if (ttsPartialFlushTimerRef.current !== null) {
          window.clearTimeout(ttsPartialFlushTimerRef.current)
          ttsPartialFlushTimerRef.current = null
        }
        spokenTextLengthRef.current = 0
        speakableStreamingTextRef.current = ''
        return null // Clear the streaming turn so the indicator goes away immediately
      })
    })

    socket.on('session_log_update', (payload: { session_id?: number }) => {
      if (payload.session_id === selectedSessionId) {
        loadSessionData(selectedSessionId)
          .then(() => {
            setOptimisticEntries([])
            setStreamingTurn(null)
          })
          .catch((error: unknown) => {
            setErrors((current) => [
              `Log refresh failed: ${error instanceof Error ? error.message : String(error)}`,
              ...current.slice(0, 3),
            ])
          })
      }
    })

    socket.on('error', (payload: SocketErrorPayload) => {
      setSendPending(false)
      setErrors((current) => [socketMessage(payload), ...current.slice(0, 3)])
    })

    socket.on('disconnect', () => {
      setSocketStatus('offline')
    })

    return () => {
      socket.emit('leave_session', {
        session_id: selectedSessionId,
        player_id: selectedPlayerId,
      })
      socket.disconnect()
      if (socketRef.current === socket) {
        socketRef.current = null
      }
    }
  }, [
    auth,
    baseUrl,
    loadSessionData,
    rememberSpokenTts,
    selectedCampaignId,
    selectedPlayerId,
    selectedSessionId,
    socketReconnectKey,
    stopTtsAudio,
  ])

  const displayCharacter = {
    name: selectedPlayer?.character_name ?? 'No player selected',
    ancestryClass: selectedPlayer
      ? `${selectedPlayer.race || 'Adventurer'} ${selectedPlayer.char_class || selectedPlayer.class_ || 'Class unset'}`
      : 'Load or create a player',
    level: selectedPlayer?.level ?? '—',
    detailId: selectedPlayer?.player_id ? `Player #${selectedPlayer.player_id}` : 'No player',
  }
  const statBlock = normalizeStats(
    playerDetail?.stats,
    playerDetail?.character_sheet,
    selectedPlayer?.level ?? null,
  )
  const xpProgress = normalizeXp(playerDetail?.character_sheet, displayCharacter.level)
  const inventoryRows = normalizeInventory(playerDetail?.inventory)
  const carriedWeight = inventoryRows.reduce(
    (total, row) => total + (row.weightValue ?? 0),
    0,
  )
  const capacity = inventoryCapacity(playerDetail?.character_sheet)
  const inventoryWeightLabel =
    capacity === null
      ? `Weight ${carriedWeight ? carriedWeight.toFixed(carriedWeight % 1 ? 1 : 0) : '—'} / — lb`
      : `Weight ${carriedWeight.toFixed(carriedWeight % 1 ? 1 : 0)} / ${capacity} lb`
  const memorySnippets = (sessionState?.memory_snippets ?? []).filter(isRecord)
  const canonFacts = memorySnippets
    .reverse()
    .map((snippet) => {
      const source = stringValue(snippet.turn_id, '—')
      const text = stripMarkdown(
        stringValue(snippet.dm_output) || stringValue(snippet.player_input),
      )
      return [
        truncateText(text || 'Memory snippet has no text.', 86),
        `S${selectedSessionId ?? '—'}E${source}`,
      ]
    })
  const visibleCanonFacts = inspectorTab === 'canon' ? canonFacts : canonFacts.slice(0, 3)
  const selectedSegment =
    segments.find((segment) => segment.is_triggered) ?? segments[0] ?? null
  const mapTitle = maps[0]?.title ?? 'No map recorded'
  const mapDescription =
    maps[0]?.description ||
    sessionState?.current_location ||
    campaign?.location ||
    'No location recorded'
  const questTitle =
    sessionState?.current_quest || campaign?.current_quest || 'No quest recorded'
  const mapPanelTitle =
    maps[0]?.title || selectedSegment?.title || (sessionState?.current_location ? 'Current Location' : mapTitle)
  const mapMeta = buildMapMeta(maps[0], selectedSegment)
  const sessionCards: SessionCard[] = sessions.map((session, index) => ({
    id: session.session_id,
    title: sessionDisplayName(session, campaign?.world_id ?? selectedCampaignId),
    meta:
      session.session_id === selectedSessionId
        ? `Active  •  Started ${formatShortAge(session.created_at)}`
        : `${index === 0 ? 'Latest' : 'Past'}  •  Started ${formatShortAge(session.created_at)}`,
  }))
  const filteredCampaigns = campaigns.filter((item) =>
    item.title.toLowerCase().includes(campaignFilter.trim().toLowerCase()),
  )
  const campaignCards: CampaignCard[] = [...filteredCampaigns]
    .sort((left, right) => {
      if (left.campaign_id === selectedCampaignId) return -1
      if (right.campaign_id === selectedCampaignId) return 1
      return 0
    })
    .map((item) => ({
      title: item.title,
      meta: `World ${item.world_id}  •  ${pluralize(campaignSessionMeta[item.campaign_id]?.count ?? 0, 'Session')}  •  Updated ${formatShortAge(campaignSessionMeta[item.campaign_id]?.updatedAt ?? item.created_at)}`,
      id: item.campaign_id,
      avatar: avatarDataUri(`${item.campaign_id}-${item.title}`),
    }))
  const lastSync = sessionState?.updated_at ?? activeSession?.created_at ?? null
  const sessionDuration = activeSession
    ? formatDurationFrom(activeSession.created_at, nowMs)
    : 'No session'
  const runtime = llmConfig?.current ?? health?.llm ?? null
  const latestRuntime = runtime?.latest_turn ?? null
  const configuredProvider = stringValue(runtime?.provider, 'Unknown')
  const configuredModel = stringValue(runtime?.model, 'Unknown')
  const runtimeProviders = llmConfig?.providers ?? []
  const selectedProviderOption = runtimeProviders.find(
    (provider) => provider.id === configuredProvider,
  )
  const runtimeModels = selectedProviderOption?.models ?? [
    { id: configuredModel, label: configuredModel },
  ]
  const backendStatusLabel =
    health === null ? 'Checking' : health.status === 'ok' ? 'Connected' : 'Offline'
  const backendStatusTone =
    health === null ? 'neutral' : health.status === 'ok' ? 'good' : 'warn'
  const runtimeLabel = runtimePending
    ? 'Switching'
    : runtime?.configured
      ? 'Live'
      : health === null
        ? 'Checking'
        : health.status === 'ok'
        ? 'Missing key'
        : 'Offline'
  const runtimeTone =
    runtimePending || health === null ? 'neutral' : runtime?.configured ? 'good' : 'warn'
  const loadedTextLength = timeline.reduce((total, entry) => total + entry.text.length, 0)
  const estimatedContextTokens = Math.round(loadedTextLength / 4)
  const contextMeterPercent = Math.min(
    100,
    Math.max(estimatedContextTokens > 0 ? 4 : 0, Math.round((estimatedContextTokens / 128000) * 100)),
  )
  const contextLabel = estimatedContextTokens
    ? `~${formatCompactNumber(estimatedContextTokens).toLowerCase()} tok`
    : 'No log'
  const responseTokenEstimate = Math.max(1, Math.round(latestDmText.length / 4))
  const executionTimeSeconds =
    latestRuntime?.latency_ms !== null && latestRuntime?.latency_ms !== undefined
      ? latestRuntime.latency_ms / 1000
      : metrics?.turn_latency_ms_avg
        ? metrics.turn_latency_ms_avg / 1000
        : 8.7
  const dmExecutionStats = {
    tokens: responseTokenEstimate || 256,
    time: `${executionTimeSeconds.toFixed(1)}s`,
    model: configuredModel || 'Unknown',
    temperature: '0.7',
  }
  const fullscreenActive = isFullscreen || fullscreenFallback

  return (
    <div
      ref={rootRef}
      className={`prototype-shell theme-${theme} ${railCollapsed ? 'rail-collapsed' : ''} ${fullscreenActive ? 'fullscreen-active' : ''}`}
    >
      <header className="ops-bar">
        <div className="ops-brand">
          <Flame size={25} fill="currentColor" />
          <strong>AI-DM</strong>
        </div>
        <button
          type="button"
          className="top-icon"
          aria-label={railCollapsed ? 'Show campaign rail' : 'Hide campaign rail'}
          aria-pressed={railCollapsed}
          onClick={() => setRailCollapsed((current) => !current)}
        >
          <Menu size={21} />
        </button>
        <div className="ops-segment backend-segment">
          <div>
            <strong>Backend</strong>
            <StatusDot label={backendStatusLabel} tone={backendStatusTone} />
          </div>
          <span>{baseUrl}</span>
          <ExternalLink size={15} />
          <button
            type="button"
            aria-label="Edit backend settings"
            title="Edit backend settings"
            onClick={openRuntimeSettingsDialog}
          >
            <Settings size={16} />
          </button>
        </div>
        <div className="ops-segment compact">
          <div>
            <strong>Provider</strong>
            <select
              className="runtime-select"
              value={configuredProvider}
              disabled={runtimePending || !runtimeProviders.length}
              title={
                latestRuntime
                  ? `Latest completed turn: ${providerLabel(latestRuntime.provider)} / ${latestRuntime.model}`
                  : 'Current runtime provider'
              }
              onChange={(event) => {
                const nextProvider = event.target.value
                const nextOption = runtimeProviders.find((provider) => provider.id === nextProvider)
                const currentModelStillAvailable = nextOption?.models.some(
                  (model) => model.id === configuredModel,
                )
                const nextModel = currentModelStillAvailable
                  ? configuredModel
                  : nextOption?.default_model || nextOption?.models[0]?.id || configuredModel
                void switchRuntime(nextProvider, nextModel)
              }}
            >
              {runtimeProviders.length ? (
                runtimeProviders.map((provider) => (
                  <option
                    key={provider.id}
                    value={provider.id}
                    disabled={!provider.configured}
                  >
                    {provider.label}
                    {provider.configured ? '' : ' (no key)'}
                  </option>
                ))
              ) : (
                <option value={configuredProvider}>{providerLabel(configuredProvider)}</option>
              )}
            </select>
            <span className="runtime-tools" aria-hidden="true">
              <ThinIcon name="cloud" size={13} />
              <ThinIcon name="refresh" size={13} />
            </span>
          </div>
          <StatusDot label={runtimeLabel} tone={runtimeTone} />
        </div>
        <div className="ops-segment compact">
          <div>
            <strong>Model</strong>
            <select
              className="runtime-select"
              value={configuredModel}
              disabled={runtimePending || !runtimeModels.length || !runtime?.configured}
              title="Current runtime model"
              onChange={(event) => {
                void switchRuntime(configuredProvider, event.target.value)
              }}
            >
              {runtimeModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.id}
                </option>
              ))}
            </select>
          </div>
          <StatusDot label={runtimeLabel} tone={runtimeTone} />
        </div>
        <div className="ops-segment context-meter">
          <div>
            <strong>Context</strong>
            <span title="Approximate text loaded in the current session log">
              {contextLabel}
            </span>
          </div>
          <div className="meter">
            <span style={{ width: `${contextMeterPercent}%` }} />
          </div>
        </div>
        <div className="ops-segment mini-stat">
          <strong>Session</strong>
          <span>{sessionDuration}</span>
        </div>
        <div className="ops-segment mini-stat">
          <Lock size={18} />
          <strong>Auto-Save</strong>
          <StatusDot label="On" />
        </div>
        <div className="ops-segment mini-stat">
          <Radio size={18} />
          <strong>Realtime</strong>
          <StatusDot label={realtimeLabel} tone={realtimeTone} />
        </div>
        <div className="ops-actions">
          <button
            type="button"
            className={`top-icon ${ttsEnabled ? 'selected' : ''} ${ttsSpeaking ? 'speaking' : ''}`}
            aria-label={ttsEnabled ? 'Turn TTS off' : 'Turn TTS on'}
            aria-pressed={ttsEnabled}
            title={
              ttsConfig?.configured
                ? `Deepgram narration: ${ttsConfig.model} (${ttsStatusLabel})`
                : 'Deepgram narration is not configured'
            }
            onClick={toggleTts}
          >
            {ttsEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
          <button
            type="button"
            className="top-icon"
            aria-label={fullscreenActive ? 'Exit fullscreen' : 'Enter fullscreen'}
            aria-pressed={fullscreenActive}
            onClick={() => void toggleFullscreen()}
          >
            {fullscreenActive ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
          </button>
          <button
            type="button"
            className="top-icon"
            aria-label="Toggle theme"
            aria-pressed={theme === 'light'}
            onClick={() => setTheme((current) => (current === 'dark' ? 'light' : 'dark'))}
          >
            <Sun size={18} />
          </button>
          <div className="account-menu-wrap" ref={accountMenuRef}>
            <button
              type="button"
              className="top-icon"
              aria-label="Account"
              aria-expanded={accountMenuOpen}
              onClick={() => setAccountMenuOpen((current) => !current)}
            >
              <UserCircle size={19} />
            </button>
            <button
              type="button"
              className="top-icon small"
              aria-label="More account options"
              aria-expanded={accountMenuOpen}
              onClick={() => setAccountMenuOpen((current) => !current)}
            >
              <ChevronDown size={16} />
            </button>
            {accountMenuOpen ? (
              <div className="account-menu">
                <strong>{selectedPlayer?.character_name ?? 'No player selected'}</strong>
                <span>{selectedPlayer?.name ?? 'Local profile'}</span>
                <button type="button" onClick={() => void refreshCurrentWorkspace()}>
                  Refresh workspace
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSocketReconnectKey((current) => current + 1)
                    setAccountMenuOpen(false)
                  }}
                >
                  Reconnect socket
                </button>
                <button type="button" onClick={openRuntimeSettingsDialog}>
                  Runtime settings
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <aside className="campaign-rail">
        <section className="rail-section">
          <div className="rail-heading">
            <span>Campaigns</span>
            <button type="button" aria-label="Add campaign" onClick={openCreateCampaignDialog}>
              <Plus size={16} />
            </button>
          </div>
          <div className="search-field">
            <ThinIcon name="spark" size={14} />
            <input
              value={campaignFilter}
              onChange={(event) => setCampaignFilter(event.target.value)}
              placeholder="Search campaigns..."
              aria-label="Search campaigns"
            />
          </div>
          <div className="campaign-list">
            {campaignCards.length ? (
              campaignCards.map((item, index) => (
                <button
                  type="button"
                  key={item.id}
                  className={`campaign-card ${item.id === selectedCampaignId ? 'active' : ''} ${
                    item.id === loadingCampaignId ? 'loading' : ''
                  }`}
                  aria-busy={item.id === loadingCampaignId}
                  onClick={() => {
                    if (item.id !== selectedCampaignId) {
                      setSelectedCampaignId(item.id)
                    }
                    setMainTab('turns')
                  }}
                >
                  <Thumbnail
                    index={index}
                    selected={item.id === selectedCampaignId}
                    src={item.avatar}
                    title={item.title}
                  />
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.meta}</small>
                  </span>
                </button>
              ))
            ) : health === null ? (
              <div className="empty-rail">Loading campaigns...</div>
            ) : (
              <div className="empty-rail">No campaigns match.</div>
            )}
          </div>
        </section>

        <section className="rail-section session-section">
          <div className="rail-heading">
            <span>Sessions ({campaign?.title ? truncateText(campaign.title, 12) : 'None'})</span>
            <button type="button" onClick={startSession} aria-label="Start session">
              <Plus size={16} />
            </button>
          </div>
          <div className="session-list">
            {sessionCards.length ? (
              sessionCards.map((session) => (
                <button
                  type="button"
                  key={session.id}
                  className={`session-card ${session.id === selectedSessionId ? 'active' : ''} ${
                    session.id === selectedSessionId && sessionLoading ? 'loading' : ''
                  }`}
                  aria-busy={session.id === selectedSessionId && sessionLoading}
                  onClick={() => {
                    if (session.id !== selectedSessionId) {
                      setSelectedSessionId(session.id)
                      setOptimisticEntries([])
                      setStreamingTurn(null)
                      setSendPending(false)
                    }
                    setMainTab('turns')
                  }}
                >
                  <strong>{session.title}</strong>
                  <small>{session.meta}</small>
                </button>
              ))
            ) : (
              <div className="empty-rail empty-action-card">
                <span>No sessions yet.</span>
                <button type="button" onClick={startSession} disabled={!selectedCampaignId}>
                  Start session
                </button>
              </div>
            )}
          </div>
        </section>

        <nav className="rail-nav">
          <NavItem
            icon={<ThinIcon name="archive" size={18} />}
            label="Campaigns"
            selected={mainTab === 'turns' && inspectorTab === 'party'}
            onClick={() => {
              setMainTab('turns')
              setInspectorTab('party')
            }}
          />
          <NavItem
            icon={<ThinIcon name="turns" size={18} />}
            label="Turns"
            selected={mainTab === 'turns'}
            onClick={() => setMainTab('turns')}
          />
          <NavItem
            icon={<ThinIcon name="map" size={18} />}
            label="Map"
            selected={inspectorTab === 'map'}
            onClick={() => setInspectorTab('map')}
          />
          <NavItem
            icon={<ThinIcon name="book" size={18} />}
            label="Canon"
            selected={inspectorTab === 'canon'}
            onClick={() => setInspectorTab('canon')}
          />
          <NavItem
            icon={<ThinIcon name="briefcase" size={18} />}
            label="Inventory"
            selected={inspectorTab === 'inventory'}
            onClick={() => setInspectorTab('inventory')}
          />
          <NavItem
            icon={<ThinIcon name="settings" size={18} />}
            label="Settings"
            selected={mainTab === 'notes'}
            onClick={() => setMainTab('notes')}
          />
        </nav>

        <footer className="rail-footer">
          <StatusDot
            label={health?.status === 'ok' ? 'All Systems Operational' : health === null ? 'Checking Backend' : 'Backend Offline'}
            tone={health?.status === 'ok' ? 'good' : health === null ? 'neutral' : 'warn'}
          />
          <span>
            Last sync: {formatShortAge(lastSync)}
            <button
              type="button"
              className="rail-sync-button"
              aria-label="Refresh workspace"
              onClick={() => void refreshCurrentWorkspace()}
            >
              <ThinIcon name="refresh" size={13} />
            </button>
          </span>
          {errors[0] ? <small className="rail-error">{errors[0]}</small> : null}
        </footer>
      </aside>

      <main className="session-board">
        <section className="session-header">
          <div>
            <h1>
              {activeSessionTitle}{' '}
              <span className={workspaceLoading || sessionLoading ? 'loading-badge' : ''}>
                {workspaceLoading || sessionLoading ? 'Loading' : 'Live'}
              </span>
            </h1>
            <p>{campaignTitle}</p>
          </div>
          <div className="session-actions">
            <ToolbarButton
              icon={<ClipboardList size={17} />}
              onClick={() => setMainTab('notes')}
              title="Summary"
            >
              Summary
            </ToolbarButton>
            <ToolbarButton
              icon={<Download size={17} />}
              onClick={() => void downloadSessionJson()}
              title="Export"
            >
              Export
            </ToolbarButton>
            <ToolbarButton icon={<Share2 size={17} />} onClick={shareSession} title="Share">
              Share
            </ToolbarButton>
            <div className="session-menu-wrap" ref={sessionMenuRef}>
              <ToolbarButton
                icon={<MoreHorizontal size={18} />}
                onClick={() => setSessionMenuOpen((current) => !current)}
                title="Session menu"
              />
              {sessionMenuOpen ? (
                <div className="session-menu">
                  <button type="button" onClick={() => void refreshCurrentWorkspace()}>
                    Refresh session
                  </button>
                  <button type="button" disabled={!activeSession} onClick={() => void renameSelectedSession()}>
                    Rename session
                  </button>
                  <button type="button" disabled={!activeSession} className="danger" onClick={() => void deleteSelectedSession()}>
                    Delete session
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </section>

        <div className="content-tabs">
          <button
            type="button"
            className={mainTab === 'turns' ? 'active' : ''}
            onClick={() => setMainTab('turns')}
          >
            Turns
          </button>
          <button
            type="button"
            className={mainTab === 'dm' ? 'active' : ''}
            onClick={() => setMainTab('dm')}
          >
            DM Response
          </button>
          <button
            type="button"
            className={mainTab === 'notes' ? 'active' : ''}
            onClick={() => setMainTab('notes')}
          >
            Notes ({memorySnippets.length})
          </button>
        </div>

        {mainTab === 'turns' ? (
          <>
          <section
            className="turn-feed"
            ref={turnFeedRef}
            onScroll={updateJumpToLatestVisibility}
          >
            {turnRows.length ? (
              turnRows.map((turn, index) => {
                const expanded = expandedTurnIds.has(turn.id)
                return (
                  <article className="turn-row" key={turn.id}>
                    <div className="turn-number">{turnNumber(turn, index)}</div>
                    <div className={`turn-card ${expanded ? 'expanded' : ''}`}>
                      <div className="turn-speaker">
                        <strong>{turn.speaker}</strong>
                        <span>{speakerDetail(turn, selectedPlayer)}</span>
                      </div>
                      <p>{expanded ? turn.text : truncateText(turn.text, 180)}</p>
                      <time>{formatClock(turn.timestamp)}</time>
                      <button
                        type="button"
                        className="turn-expand"
                        aria-label={expanded ? 'Collapse turn' : 'Expand turn'}
                        aria-expanded={expanded}
                        onClick={() => {
                          setExpandedTurnIds((current) => {
                            const next = new Set(current)
                            if (next.has(turn.id)) {
                              next.delete(turn.id)
                            } else {
                              next.add(turn.id)
                            }
                            return next
                          })
                        }}
                      >
                        <ChevronDown size={18} />
                      </button>
                    </div>
                  </article>
                )
              })
            ) : (
              <div className="empty-state">
                {activeSession ? welcomeText : 'No turn log entries loaded for this session.'}
              </div>
            )}

            <article className="turn-row current">
              <div className="turn-number">
                {currentResponseEntry ? turnNumber(currentResponseEntry, turnRows.length) : '—'}
              </div>
              <div className="dm-response-card">
                <div className="turn-speaker">
                  <strong>{currentResponseEntry?.speaker ?? 'DM'}</strong>
                  <span>{currentResponseEntry?.streaming ? 'Streaming' : 'Latest Response'}</span>
                </div>
                <div className="response-copy">
                  <p>{latestDmText}</p>
                </div>
                <div className={`stream-state ${sendPending || streamingTurn ? 'streaming' : ''}`}>
                  <span />
                  {sendPending || streamingTurn ? 'Streaming...' : 'Ready'}
                </div>
                <div className="execution-footer">
                  Tokens: {dmExecutionStats.tokens} <span>|</span> Time: {dmExecutionStats.time}{' '}
                  <span>|</span> Model: {dmExecutionStats.model} <span>|</span> Temp:{' '}
                  {dmExecutionStats.temperature}
                </div>
              </div>
            </article>
          </section>
          {showJumpToLatest ? (
            <button
              type="button"
              className="jump-latest-button"
              onClick={scrollTurnFeedToLatest}
            >
              <ArrowDown size={14} />
              Latest
            </button>
          ) : null}
          </>
        ) : null}

        {mainTab === 'dm' ? (
          <section className="turn-feed single-panel">
            <article className="turn-row current">
              <div className="turn-number">
                {currentResponseEntry ? turnNumber(currentResponseEntry, 0) : '—'}
              </div>
              <div className="dm-response-card expanded">
                <div className="turn-speaker">
                  <strong>{currentResponseEntry?.speaker ?? 'DM'}</strong>
                  <span>Full Response</span>
                </div>
                <div className="response-copy">
                  <p>{latestDmText}</p>
                </div>
                <div className={`stream-state ${sendPending || streamingTurn ? 'streaming' : ''}`}>
                  <span />
                  {sendPending || streamingTurn ? 'Streaming...' : 'Ready'}
                </div>
                <div className="execution-footer">
                  Tokens: {dmExecutionStats.tokens} <span>|</span> Time: {dmExecutionStats.time}{' '}
                  <span>|</span> Model: {dmExecutionStats.model} <span>|</span> Temp:{' '}
                  {dmExecutionStats.temperature}
                </div>
              </div>
            </article>
          </section>
        ) : null}

        {mainTab === 'notes' ? (
          <section className="turn-feed notes-panel">
            <div className="notes-card">
              <h2>Session State</h2>
              <dl>
                <dt>Current quest</dt>
                <dd>{questTitle}</dd>
                <dt>Current location</dt>
                <dd>{sessionState?.current_location || campaign?.location || 'No location recorded'}</dd>
                <dt>Updated</dt>
                <dd>{formatDateTime(sessionState?.updated_at ?? null)}</dd>
              </dl>
              <h3>Rolling Summary</h3>
              <p>{sessionState?.rolling_summary || 'No rolling summary recorded yet.'}</p>
            </div>
            <div className="notes-card compact-notes">
              <h3>Recent Memory</h3>
              {canonFacts.length ? (
                canonFacts.slice(0, 5).map(([fact, source]) => (
                  <div key={`${fact}-${source}`} className="note-line">
                    <ThinIcon name="dot" size={12} />
                    <span>{fact}</span>
                    <small>{source}</small>
                  </div>
                ))
              ) : (
                <p>No memory snippets recorded yet.</p>
              )}
            </div>
          </section>
        ) : null}

        <section className="action-composer">
          <label htmlFor="action-input">
            Your Action <span>({composerModeLabel(composerMode, selectedDie)})</span>
          </label>
          <div className={`tts-status-strip ${effectiveTtsStatus}`} role="status" aria-live="polite">
            <span>
              {ttsEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
              Narration <strong>{ttsStatusLabel}</strong>
            </span>
            {canStopTts ? (
              <button type="button" onClick={stopTtsAudio}>
                <X size={14} />
                Stop
              </button>
            ) : null}
          </div>
          <div className="composer-frame">
            <textarea
              id="action-input"
              value={actionText}
              onChange={(event) => setActionText(event.target.value)}
              placeholder={
                selectedPlayer
                  ? 'Write your action...'
                  : 'Choose a player before sending.'
              }
              rows={4}
            />
            <div className="input-action-row">
              <div className="mode-buttons">
                <button
                  type="button"
                  aria-label="Dice mode"
                  className={composerMode === 'roll' ? 'selected' : ''}
                  onClick={() => startDiceRoll()}
                  onFocus={preloadDiceRollDialog}
                  onMouseEnter={preloadDiceRollDialog}
                  disabled={sendPending}
                >
                  <ThinIcon name="dice" size={18} />
                </button>
                <button
                  type="button"
                  aria-label="Action mode"
                  className={composerMode === 'action' ? 'selected' : ''}
                  onClick={() => applyComposerMode('action')}
                >
                  <ThinIcon name="bolt" size={18} />
                </button>
                <button
                  type="button"
                  aria-label="OOC mode"
                  className={composerMode === 'ooc' ? 'selected' : ''}
                  onClick={() => applyComposerMode('ooc')}
                >
                  <ThinIcon name="chevron" size={17} />
                </button>
              </div>
              <button
                type="button"
                className="send-button"
                onClick={() => submitAction()}
                disabled={sendPending || !actionText.trim()}
              >
                <ThinIcon name="send" size={18} />
                Send
              </button>
            </div>
          </div>
          <div className="composer-tools">
            <button
              type="button"
              className={composerMode === 'roll' ? 'selected' : ''}
              onClick={() => startDiceRoll()}
              onFocus={preloadDiceRollDialog}
              onMouseEnter={preloadDiceRollDialog}
              disabled={sendPending}
            >
              <ThinIcon name="dice" size={16} /> Roll <ThinIcon name="chevron" size={13} />
            </button>
            <select
              className="dice-select"
              value={selectedDie}
              aria-label="Select die"
              onChange={(event) => updateSelectedDie(event.target.value)}
            >
              {DICE_OPTIONS.map((die) => (
                <option key={die} value={die}>
                  {die.toUpperCase()}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={composerMode === 'ability' ? 'selected' : ''}
              onClick={() => applyComposerMode('ability')}
            >
              <ThinIcon name="bolt" size={16} /> Ability
            </button>
            <button
              type="button"
              className={composerMode === 'item' ? 'selected' : ''}
              onClick={() => applyComposerMode('item')}
            >
              <ThinIcon name="briefcase" size={16} /> Item
            </button>
            <button
              type="button"
              className={composerMode === 'emote' ? 'selected' : ''}
              onClick={() => applyComposerMode('emote')}
            >
              <ThinIcon name="smile" size={16} /> Emote
            </button>
            <button
              type="button"
              className={composerMode === 'ooc' ? 'selected' : ''}
              onClick={() => applyComposerMode('ooc')}
            >
              <ThinIcon name="dot" size={16} /> OOC
            </button>
          </div>
        </section>
      </main>

      <aside className="right-inspector">
        <div className="inspector-tabs">
          <button
            type="button"
            className={inspectorTab === 'party' ? 'active' : ''}
            onClick={() => setInspectorTab('party')}
          >
            Party
          </button>
          <button
            type="button"
            className={inspectorTab === 'map' ? 'active' : ''}
            onClick={() => setInspectorTab('map')}
          >
            Map
          </button>
          <button
            type="button"
            className={inspectorTab === 'canon' ? 'active' : ''}
            onClick={() => setInspectorTab('canon')}
          >
            Canon
          </button>
          <button
            type="button"
            className={inspectorTab === 'inventory' ? 'active' : ''}
            onClick={() => setInspectorTab('inventory')}
          >
            Inventory
          </button>
        </div>

        {(inspectorTab === 'party' || inspectorTab === 'inventory') ? (
          <section className="character-panel">
            <div className="character-card">
              <div className="portrait">
                <img
                  src={avatarDataUri(displayCharacter.name, 'character')}
                  alt=""
                  aria-hidden="true"
                />
              </div>
              <div className="character-main">
                <div>
                  <h2>{displayCharacter.name}</h2>
                  <p>{displayCharacter.ancestryClass}</p>
                </div>
                <div className="level-stack">
                  <span>Level</span>
                  <strong>{displayCharacter.level}</strong>
                </div>
                <div className="xp-track">
                  <span style={{ width: `${xpProgress.percent}%` }} />
                </div>
                <div className="xp-label">
                  <span>{displayCharacter.detailId}</span>
                  <small>{xpProgress.label}</small>
                </div>
              </div>
            </div>
            {!players.length ? (
              <div className="empty-inline-action">
                <span>No players in this campaign yet.</span>
                <button
                  type="button"
                  onClick={() => void createDefaultPlayer()}
                  disabled={!selectedCampaignId || createPlayerPending}
                >
                  {createPlayerPending ? 'Creating...' : 'Create player'}
                </button>
              </div>
            ) : null}

            <div className="vital-grid">
              <div>
                <span>HP</span>
                <strong className="hp">{displayStatValue(statBlock.hp)}</strong>
              </div>
              <div>
                <span>AC</span>
                <strong>{displayStatValue(statBlock.ac)}</strong>
              </div>
              <div>
                <span>INIT</span>
                <strong>{displayStatValue(statBlock.init)}</strong>
              </div>
              <div>
                <span>SPEED</span>
                <strong>{displayStatValue(statBlock.speed)}</strong>
              </div>
            </div>

            <div className="ability-grid">
              {statBlock.abilities.map(([label, score, mod]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{displayStatValue(score)}</strong>
                  <small>{displayStatValue(mod)}</small>
                </div>
              ))}
            </div>

            <div className="inspiration-row">
              <span>Inspiration</span>
              <button
                type="button"
                className={`inspiration-toggle ${statBlock.inspiration ? 'filled' : ''}`}
                aria-label="Inspiration"
              />
              <span>Proficiency</span>
              <strong>{displayStatValue(statBlock.proficiency)}</strong>
            </div>
          </section>
        ) : null}

        {(inspectorTab === 'party' || inspectorTab === 'inventory') ? (
          <section className="inspector-box">
            <div className="box-title">
              <h3>Inventory ({inventoryRows.length})</h3>
              <span>{inventoryWeightLabel}</span>
            </div>
            <div className="inventory-table">
              {inventoryRows.length ? (
                inventoryRows.slice(0, inspectorTab === 'inventory' ? 8 : 4).map((item, index) => (
                  <div key={`${item.item}-${index}`}>
                    <span className={`item-icon ${item.icon}`}>
                      <ThinIcon name={item.icon === 'shield' ? 'archive' : item.icon === 'potion' ? 'dot' : item.icon === 'armor' ? 'briefcase' : 'spark'} size={15} />
                    </span>
                    <strong>{item.item}</strong>
                    <span>{item.count}</span>
                    <span>{item.weight}</span>
                  </div>
                ))
              ) : (
                <div className="empty-row">No inventory recorded.</div>
              )}
            </div>
            <button type="button" className="view-link" onClick={() => setInspectorTab('inventory')}>
              View All Inventory <ExternalLink size={12} />
            </button>
          </section>
        ) : null}

        {(inspectorTab === 'party' || inspectorTab === 'canon') ? (
          <section className="inspector-box">
            <div className="box-title">
              <h3>Canon Facts ({memorySnippets.length})</h3>
              <span>{inspectorTab === 'canon' ? 'All' : 'Recent'} <ChevronDown size={14} /></span>
            </div>
            <div className="canon-list">
              {visibleCanonFacts.length ? (
                visibleCanonFacts.map(([fact, source]) => (
                  <div key={`${fact}-${source}`}>
                    <ThinIcon name="dot" size={12} />
                    <span>{fact}</span>
                    <small>{source}</small>
                  </div>
                ))
              ) : (
                <div className="empty-row">No memory snippets recorded.</div>
              )}
            </div>
            <button
              type="button"
              className="view-link"
              onClick={() => {
                setInspectorTab('canon')
                setMainTab('notes')
              }}
            >
              View All Canon <ExternalLink size={12} />
            </button>
          </section>
        ) : null}

        {(inspectorTab === 'party' || inspectorTab === 'map') ? (
          <section className="inspector-box">
            <div className="box-title">
              <h3>Current Map / Segment</h3>
              <button
                type="button"
                onClick={() => {
                  setInspectorTab('map')
                }}
              >
                Change
              </button>
            </div>
            <div className="map-segment">
              <div className="mini-map">
                <span />
              </div>
              <div className="map-meta-column">
                <h4>{mapPanelTitle}</h4>
                <p>{mapDescription}</p>
                <dl>
                  <dt>Explored</dt>
                  <dd>{mapMeta.explored}</dd>
                  <dt>Threat</dt>
                  <dd className={`threat-${mapMeta.threatTone}`}>{mapMeta.threat}</dd>
                  <dt>Weather</dt>
                  <dd>{mapMeta.weather}</dd>
                </dl>
                <small>{truncateText(questTitle, 30)} / {selectedSegment?.title ? truncateText(selectedSegment.title, 30) : 'None'}</small>
              </div>
            </div>
            {!maps.length ? (
              <div className="empty-inline-action">
                <span>No campaign map has been recorded.</span>
                <button
                  type="button"
                  onClick={() => void createDefaultMap()}
                  disabled={!selectedCampaignId || !campaign || createMapPending}
                >
                  {createMapPending ? 'Creating...' : 'Create map'}
                </button>
              </div>
            ) : null}
          </section>
        ) : null}

      </aside>

      {diceRoll ? (
        <div
          className="modal-backdrop dice-roll-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && diceRoll.status === 'rolling') {
              setDiceRoll(null)
            }
          }}
        >
          <Suspense
            fallback={
              <section className="dice-dialog dice-loading" role="status" aria-live="polite">
                <div className="dice-loading-body">
                  <strong>Preparing dice...</strong>
                  <span>{diceRoll.die.toUpperCase()}</span>
                </div>
              </section>
            }
          >
            <DiceRollDialog
              die={diceRoll.die}
              result={diceRoll.result}
              rollKey={diceRoll.rollKey}
              status={diceRoll.status}
              onCancel={() => {
                if (diceRoll.status === 'rolling') {
                  setDiceRoll(null)
                }
              }}
              onComplete={completeDiceRoll}
            />
          </Suspense>
        </div>
      ) : null}

      {runtimeSettingsOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeRuntimeSettingsDialog()
            }
          }}
        >
          <section
            className="campaign-dialog runtime-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="runtime-settings-title"
          >
            <header>
              <div>
                <span>Runtime</span>
                <h2 id="runtime-settings-title">Backend Settings</h2>
              </div>
              <button
                type="button"
                aria-label="Close backend settings"
                onClick={closeRuntimeSettingsDialog}
              >
                <X size={18} />
              </button>
            </header>
            <form onSubmit={submitRuntimeSettings}>
              <label>
                Backend URL
                <input
                  autoFocus
                  value={runtimeSettingsForm.baseUrl}
                  onChange={(event) =>
                    setRuntimeSettingsForm((current) => ({
                      ...current,
                      baseUrl: event.target.value,
                    }))
                  }
                  placeholder="http://127.0.0.1:5050"
                />
              </label>
              <label>
                Auth Token
                <input
                  value={runtimeSettingsForm.authToken}
                  onChange={(event) =>
                    setRuntimeSettingsForm((current) => ({
                      ...current,
                      authToken: event.target.value,
                    }))
                  }
                  placeholder="Optional bearer token"
                  type="password"
                  autoComplete="off"
                />
              </label>
              <p>
                These settings are saved locally in this browser and used for API,
                Socket.IO, and TTS requests.
              </p>
              {runtimeSettingsError ? (
                <div className="dialog-error">{runtimeSettingsError}</div>
              ) : null}
              <footer>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    setRuntimeSettingsForm({ baseUrl: DEFAULT_BASE_URL, authToken: '' })
                  }
                >
                  Reset
                </button>
                <button type="button" className="secondary" onClick={closeRuntimeSettingsDialog}>
                  Cancel
                </button>
                <button type="submit">Save Settings</button>
              </footer>
            </form>
          </section>
        </div>
      ) : null}

      {createCampaignOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeCreateCampaignDialog()
            }
          }}
        >
          <section
            className="campaign-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-campaign-title"
          >
            <header>
              <div>
                <span>Campaign</span>
                <h2 id="create-campaign-title">Create New Campaign</h2>
              </div>
              <button
                type="button"
                aria-label="Close create campaign"
                onClick={closeCreateCampaignDialog}
              >
                <X size={18} />
              </button>
            </header>
            <form onSubmit={(event) => void submitCreateCampaign(event)}>
              <label>
                Campaign Name
                <input
                  autoFocus
                  value={createCampaignForm.title}
                  onChange={(event) =>
                    setCreateCampaignForm((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  placeholder="Ashes Beyond the Gate"
                  disabled={createCampaignPending}
                />
              </label>
              <label>
                Description
                <textarea
                  value={createCampaignForm.description}
                  onChange={(event) =>
                    setCreateCampaignForm((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                  rows={3}
                  placeholder="Opening premise, party goal, or tone..."
                  disabled={createCampaignPending}
                />
              </label>
              <label>
                World
                <input
                  value={createCampaignForm.worldName}
                  onChange={(event) =>
                    setCreateCampaignForm((current) => ({
                      ...current,
                      worldName: event.target.value,
                    }))
                  }
                  placeholder={
                    campaigns.length
                      ? `Leave blank to use world ${campaign?.world_id ?? campaigns[0]?.world_id}`
                      : 'New world name'
                  }
                  disabled={createCampaignPending}
                />
              </label>
              <p>
                {campaigns.length
                  ? `Blank world uses the selected campaign world (${campaign?.world_id ?? campaigns[0]?.world_id}).`
                  : 'A new world will be created for this campaign.'}
              </p>
              {createCampaignError ? (
                <div className="dialog-error">{createCampaignError}</div>
              ) : null}
              <footer>
                <button
                  type="button"
                  className="secondary"
                  onClick={closeCreateCampaignDialog}
                  disabled={createCampaignPending}
                >
                  Cancel
                </button>
                <button type="submit" disabled={createCampaignPending}>
                  {createCampaignPending ? 'Creating...' : 'Create Campaign'}
                </button>
              </footer>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  )
}

export default App
