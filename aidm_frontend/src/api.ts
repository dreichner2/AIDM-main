import type { JsonRecord } from './types'

export class ApiClientError extends Error {
  status: number
  payload: unknown

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
    this.payload = payload
  }
}

export function normalizeBaseUrl(value: string) {
  const trimmed = value.trim()
  return trimmed.endsWith('/') ? trimmed.slice(0, -1) : trimmed
}

const NGROK_BROWSER_WARNING_HEADER = 'ngrok-skip-browser-warning'

function shouldBypassNgrokBrowserWarning(baseUrl: string) {
  try {
    const hostname = new URL(normalizeBaseUrl(baseUrl)).hostname
    return hostname.endsWith('.ngrok-free.app') || hostname.endsWith('.ngrok.app')
  } catch {
    return baseUrl.includes('.ngrok-free.app') || baseUrl.includes('.ngrok.app')
  }
}

export function ngrokBrowserWarningBypassHeaders(baseUrl: string): Record<string, string> | undefined {
  if (!shouldBypassNgrokBrowserWarning(baseUrl)) return undefined
  return { [NGROK_BROWSER_WARNING_HEADER]: 'true' }
}

export function addNgrokBrowserWarningBypassHeader(headers: Headers, baseUrl: string) {
  const bypassHeaders = ngrokBrowserWarningBypassHeaders(baseUrl)
  if (!bypassHeaders) return
  for (const [name, value] of Object.entries(bypassHeaders)) {
    headers.set(name, value)
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function errorMessage(payload: unknown, fallback: string) {
  if (isRecord(payload)) {
    if (typeof payload.error === 'string') return payload.error
    if (typeof payload.message === 'string') return payload.message
  }
  return fallback
}

function parseResponsePayload(text: string, response: Response) {
  if (!text) return null

  const contentType = response.headers.get('Content-Type') ?? ''
  if (!contentType.toLowerCase().includes('json')) {
    return { raw: text }
  }

  try {
    return JSON.parse(text) as unknown
  } catch {
    return { raw: text }
  }
}

export async function apiFetch<T>(
  baseUrl: string,
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  if (token.trim()) {
    headers.set('Authorization', `Bearer ${token.trim()}`)
  }
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  addNgrokBrowserWarningBypassHeader(headers, baseUrl)

  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    ...options,
    headers,
  })
  const text = await response.text()
  const payload = parseResponsePayload(text, response)

  if (!response.ok) {
    throw new ApiClientError(
      errorMessage(payload, `Request failed with status ${response.status}`),
      response.status,
      payload,
    )
  }

  return payload as T
}
