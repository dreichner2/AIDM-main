import { useCallback, useState, type FormEvent } from 'react'
import { normalizeBaseUrl } from './api'

export type RuntimeSettingsForm = {
  baseUrl: string
  authToken: string
}

export type RuntimeSettingsMode = 'settings' | 'auth'

function loadSessionAuthToken() {
  const sessionToken = sessionStorage.getItem('aidm:authToken')
  if (sessionToken !== null) return sessionToken
  const legacyToken = localStorage.getItem('aidm:authToken') ?? ''
  if (legacyToken) {
    sessionStorage.setItem('aidm:authToken', legacyToken)
    localStorage.removeItem('aidm:authToken')
  }
  return legacyToken
}

function storeSessionAuthToken(value: string) {
  const token = value.trim()
  localStorage.removeItem('aidm:authToken')
  if (token) {
    sessionStorage.setItem('aidm:authToken', token)
  } else {
    sessionStorage.removeItem('aidm:authToken')
  }
}

function isHttpBaseUrl(value: string) {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol)
  } catch {
    return false
  }
}

function queryRuntimeBaseUrl() {
  const params = new URLSearchParams(window.location.search)
  const value = params.get('backend') ?? params.get('api')
  const baseUrl = value ? normalizeBaseUrl(value) : ''
  return baseUrl && isHttpBaseUrl(baseUrl) ? baseUrl : ''
}

function loadInitialBaseUrl(defaultBaseUrl: string) {
  const queryBaseUrl = queryRuntimeBaseUrl()
  if (queryBaseUrl) {
    localStorage.setItem('aidm:baseUrl', queryBaseUrl)
    return queryBaseUrl
  }
  return normalizeBaseUrl(localStorage.getItem('aidm:baseUrl') ?? defaultBaseUrl)
}

type UseRuntimeSettingsOptions = {
  defaultBaseUrl: string
  resetRuntimeState: () => void
  reconnectSocket: () => void
}

export function useRuntimeSettings({
  defaultBaseUrl,
  resetRuntimeState,
  reconnectSocket,
}: UseRuntimeSettingsOptions) {
  const [baseUrl, setBaseUrl] = useState(() => loadInitialBaseUrl(defaultBaseUrl))
  const [authToken, setAuthToken] = useState(() => loadSessionAuthToken())
  const [runtimeSettingsOpen, setRuntimeSettingsOpen] = useState(false)
  const [runtimeSettingsMode, setRuntimeSettingsMode] = useState<RuntimeSettingsMode>('settings')
  const [runtimeSettingsError, setRuntimeSettingsError] = useState('')
  const [runtimeSettingsForm, setRuntimeSettingsForm] = useState<RuntimeSettingsForm>(() => ({
    baseUrl: loadInitialBaseUrl(defaultBaseUrl),
    authToken: loadSessionAuthToken(),
  }))

  const openRuntimeSettings = useCallback((mode: RuntimeSettingsMode = 'settings') => {
    setRuntimeSettingsForm({ baseUrl, authToken })
    setRuntimeSettingsMode(mode)
    setRuntimeSettingsError('')
    setRuntimeSettingsOpen(true)
  }, [authToken, baseUrl])

  const openAuthTokenPrompt = useCallback(() => {
    openRuntimeSettings('auth')
  }, [openRuntimeSettings])

  const closeRuntimeSettings = useCallback(() => {
    setRuntimeSettingsOpen(false)
    setRuntimeSettingsMode('settings')
    setRuntimeSettingsError('')
  }, [])

  const submitRuntimeSettings = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const nextBaseUrl = normalizeBaseUrl(runtimeSettingsForm.baseUrl)
      const nextAuthToken = runtimeSettingsForm.authToken.trim()

      if (!nextBaseUrl) {
        localStorage.removeItem('aidm:baseUrl')
        storeSessionAuthToken(nextAuthToken)

        setBaseUrl('')
        setAuthToken(nextAuthToken)
        resetRuntimeState()
        reconnectSocket()
        setRuntimeSettingsOpen(false)
        setRuntimeSettingsMode('settings')
        setRuntimeSettingsError('')
        return
      }

      if (!isHttpBaseUrl(nextBaseUrl)) {
        setRuntimeSettingsError('Backend URL must start with http:// or https://.')
        return
      }

      localStorage.setItem('aidm:baseUrl', nextBaseUrl)
      storeSessionAuthToken(nextAuthToken)

      setBaseUrl(nextBaseUrl)
      setAuthToken(nextAuthToken)
      resetRuntimeState()
      reconnectSocket()
      setRuntimeSettingsOpen(false)
      setRuntimeSettingsMode('settings')
      setRuntimeSettingsError('')
    },
    [reconnectSocket, resetRuntimeState, runtimeSettingsForm.authToken, runtimeSettingsForm.baseUrl],
  )

  const clearAuthToken = useCallback(() => {
    storeSessionAuthToken('')
    setAuthToken('')
    setRuntimeSettingsForm((current) => ({ ...current, authToken: '' }))
    reconnectSocket()
  }, [reconnectSocket])

  return {
    authToken,
    baseUrl,
    clearAuthToken,
    closeRuntimeSettings,
    openAuthTokenPrompt,
    openRuntimeSettings,
    runtimeSettingsError,
    runtimeSettingsForm,
    runtimeSettingsMode,
    runtimeSettingsOpen,
    setRuntimeSettingsForm,
    submitRuntimeSettings,
  }
}
