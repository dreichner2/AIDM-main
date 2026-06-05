export type JsonRecord = Record<string, unknown>

export type Health = {
  status: string
  service: string
  env: string
  auth_required: boolean
  rules_engine_enabled: boolean
  segment_evaluator_enabled: boolean
  llm?: {
    provider: string
    model: string
    fallback_models: string[]
    configured?: boolean
    latest_turn: {
      turn_id: number
      session_id: number
      provider: string
      model: string
      latency_ms: number | null
      completed_at: string | null
    } | null
  }
}

export type LlmModelOption = {
  id: string
  label: string
}

export type LlmProviderOption = {
  id: string
  label: string
  default_model: string
  configured: boolean
  base_url?: string
  models: LlmModelOption[]
}

export type LlmRuntimeConfig = {
  current: NonNullable<Health['llm']>
  providers: LlmProviderOption[]
  persisted: boolean
}

export type TtsRuntimeConfig = {
  provider: 'deepgram'
  configured: boolean
  model: string
}

export type Campaign = {
  campaign_id: number
  title: string
  description: string
  world_id: number
  created_at: string | null
  current_quest?: string | null
  location?: string | null
  session_count?: number
  latest_session_id?: number | null
  latest_activity_at?: string | null
}

export type World = {
  world_id: number
  name: string
  description: string
  created_at: string | null
}

export type SessionSummary = {
  session_id: number
  campaign_id: number
  created_at: string | null
  updated_at?: string | null
  latest_activity_at?: string | null
  display_name?: string
  turn_count?: number
  latest_summary?: string
  is_archived?: boolean
  state_snapshot: JsonRecord | null
}

export type CampaignWorkspace = {
  campaign: Campaign
  sessions: SessionSummary[]
  players: Player[]
  maps: MapItem[]
  segments: CampaignSegment[]
  summary: {
    session_count: number
    player_count: number
    map_count: number
    segment_count: number
    latest_session_id: number | null
    latest_activity_at: string | null
  }
}

export type CampaignCanon = {
  campaign_id: number
  entities: JsonRecord[]
  facts: JsonRecord[]
  threads: JsonRecord[]
  updates: JsonRecord[]
  summary: JsonRecord
}

export type SessionLogEntry = {
  id: number
  message: string
  entry_type: string
  metadata: JsonRecord
  timestamp: string | null
}

export type SessionLogResponse = {
  session_id: number
  entries: SessionLogEntry[]
}

export type TurnEventPayload = {
  event_id: number
  session_id: number
  campaign_id: number
  turn_id: number | null
  player_id: number | null
  event_type: string
  payload: JsonRecord
  created_at: string | null
}

export type SessionEventsResponse = {
  session_id: number
  events: TurnEventPayload[]
}

export type SessionState = {
  session_id: number
  campaign_id: number
  current_location: string | null
  current_quest: string | null
  rolling_summary: string
  active_segments: unknown[]
  memory_snippets: unknown[]
  updated_at: string | null
}

export type Player = {
  player_id: number
  campaign_id: number
  name: string
  character_name: string
  race: string
  class_: string
  char_class: string
  level: number
}

export type PlayerDetail = Player & {
  stats: unknown
  inventory: unknown
  character_sheet: unknown
}

export type MapItem = {
  map_id: number
  world_id: number | null
  campaign_id: number | null
  title: string
  description: string
  map_data: JsonRecord
  created_at: string | null
}

export type CampaignSegment = {
  segment_id: number
  campaign_id: number
  title: string
  description: string
  trigger_condition: string
  tags: string
  is_triggered: boolean
  created_at: string | null
}

export type BetaSummary = {
  turn_latency_ms_avg: number | null
  ai_failure_rate: number
  session_completion_rate: number
  coherence_feedback_avg: number | null
  coherence_feedback_count: number
  total_turns: number
  total_sessions: number
}

export type ActivePlayer = {
  id: number
  character_name: string
  name: string
}

export type RulesHint = {
  roll_type?: string | null
  dc_hint?: string | null
  reason?: string | null
  confidence?: number | null
  roll_value?: number | null
  outcome_deferred?: boolean | null
}

export type SocketErrorPayload = {
  error?: string
  message?: string
  error_code?: string
  details?: JsonRecord
}

export type TimelineRole = 'dm' | 'player' | 'system'

export type TimelineEntry = {
  id: string
  role: TimelineRole
  speaker: string
  text: string
  timestamp: string | null
  metadata: JsonRecord
  streaming?: boolean
}

export type StreamingTurn = {
  turnId: number
  text: string
  requiresRoll: boolean
  rulesHint: RulesHint
}
