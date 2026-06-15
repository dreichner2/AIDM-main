import { useCallback, useEffect, useState } from 'react'
import { ApiClientError, apiFetch } from './api'
import type { BetaIncidentsResponse, JsonRecord } from './types'

type BetaIncidentPanelProps = {
  baseUrl: string
  auth: string
}

const INCIDENT_LIMIT = 20

const INCIDENT_TYPE_LABELS: Record<string, string> = {
  failed_turn: 'Failed Turn',
  failed_canon_job: 'Failed Canon Job',
  bad_turn_report: 'Bad-Turn Report',
  telemetry_event: 'Telemetry Event',
}

function textValue(value: unknown, fallback = '') {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function incidentTypeLabel(incident: JsonRecord) {
  const type = textValue(incident.type, 'incident')
  return INCIDENT_TYPE_LABELS[type] ?? type.replace(/_/g, ' ')
}

function incidentSeverity(incident: JsonRecord) {
  const severity = textValue(incident.severity, 'medium').toLowerCase()
  return ['low', 'medium', 'high'].includes(severity) ? severity : 'medium'
}

function incidentMessage(incident: JsonRecord) {
  return textValue(incident.message, textValue(incident.event_name, 'Incident recorded.'))
}

function incidentKey(incident: JsonRecord, index: number) {
  return [
    incident.type,
    incident.turn_id,
    incident.job_id,
    incident.feedback_id,
    incident.event_name,
    index,
  ].filter((part) => part !== undefined && part !== null && part !== '').join(':')
}

function formatTime(value: unknown) {
  const text = textValue(value)
  if (!text) return ''
  const date = new Date(text)
  if (Number.isNaN(date.getTime())) return text
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function incidentMeta(incident: JsonRecord) {
  const meta = []
  const campaignId = numberValue(incident.campaign_id)
  const sessionId = numberValue(incident.session_id)
  const turnId = numberValue(incident.turn_id)
  const jobId = numberValue(incident.job_id)
  const feedbackId = numberValue(incident.feedback_id)
  const count = numberValue(incident.count)
  const provider = textValue(incident.provider)
  const model = textValue(incident.model)
  const category = textValue(incident.category)
  const latencyMs = numberValue(incident.latency_ms)
  if (campaignId !== null) meta.push(`campaign ${campaignId}`)
  if (sessionId !== null) meta.push(`session ${sessionId}`)
  if (turnId !== null) meta.push(`turn ${turnId}`)
  if (jobId !== null) meta.push(`job ${jobId}`)
  if (feedbackId !== null) meta.push(`feedback ${feedbackId}`)
  if (provider || model) meta.push([provider, model].filter(Boolean).join(' / '))
  if (category) meta.push(category)
  if (latencyMs !== null) meta.push(`${latencyMs} ms`)
  if (count !== null) meta.push(`${count} event${count === 1 ? '' : 's'}`)
  return meta
}

export function BetaIncidentPanel({ baseUrl, auth }: BetaIncidentPanelProps) {
  const [incidents, setIncidents] = useState<BetaIncidentsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadIncidents = useCallback(async (cancelled?: () => boolean) => {
    if (cancelled?.()) return
    setLoading(true)
    setError('')
    try {
      const payload = await apiFetch<BetaIncidentsResponse>(
        baseUrl,
        `/api/beta/incidents?limit=${INCIDENT_LIMIT}`,
        auth,
      )
      if (!cancelled?.()) setIncidents(payload)
    } catch (loadError) {
      const message =
        loadError instanceof ApiClientError && loadError.status === 403
          ? 'Workspace admin access is required.'
          : loadError instanceof Error
            ? loadError.message
            : String(loadError)
      if (!cancelled?.()) setError(message)
    } finally {
      if (!cancelled?.()) setLoading(false)
    }
  }, [auth, baseUrl])

  useEffect(() => {
    let cancelled = false
    void Promise.resolve().then(() => loadIncidents(() => cancelled))
    return () => {
      cancelled = true
    }
  }, [loadIncidents])

  const summary = incidents?.summary
  const incidentRows = incidents?.incidents ?? []

  return (
    <section className="inspector-box beta-incident-panel" aria-label="Beta incidents">
      <div className="box-title">
        <h3>Beta Incidents</h3>
        <button type="button" onClick={() => void loadIncidents()} disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="incident-summary-grid" aria-label="Incident summary">
        <div>
          <span>Turns</span>
          <strong>{summary?.failed_turn_count ?? 0}</strong>
        </div>
        <div>
          <span>Canon</span>
          <strong>{summary?.failed_canon_job_count ?? 0}</strong>
        </div>
        <div>
          <span>Reports</span>
          <strong>{summary?.bad_turn_report_count ?? 0}</strong>
        </div>
        <div>
          <span>Events</span>
          <strong>{summary?.telemetry_incident_count ?? 0}</strong>
        </div>
      </div>

      {error ? <div className="bestiary-message error">{error}</div> : null}
      {!error && loading && !incidents ? <div className="empty-row">Loading incidents...</div> : null}
      {!error && !loading && incidents && !incidentRows.length ? (
        <div className="empty-row">No beta incidents recorded.</div>
      ) : null}

      <div className="incident-list" aria-label="Beta incident list">
        {incidentRows.map((incident, index) => {
          const severity = incidentSeverity(incident)
          const meta = incidentMeta(incident)
          const createdAt = formatTime(incident.created_at)
          return (
            <article key={incidentKey(incident, index)} className={`incident-card severity-${severity}`}>
              <div className="incident-card-title">
                <strong>{incidentTypeLabel(incident)}</strong>
                <span>{severity}</span>
              </div>
              <p>{incidentMessage(incident)}</p>
              {meta.length ? (
                <div className="incident-meta">
                  {meta.map((item) => <span key={item}>{item}</span>)}
                </div>
              ) : null}
              {createdAt ? <time>{createdAt}</time> : null}
            </article>
          )
        })}
      </div>
    </section>
  )
}
