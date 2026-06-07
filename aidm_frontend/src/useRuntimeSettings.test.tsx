// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import type { FormEvent } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useRuntimeSettings } from './useRuntimeSettings'

function submitEvent() {
  return {
    preventDefault: vi.fn(),
  } as unknown as FormEvent<HTMLFormElement>
}

function createStorageMock(): Storage {
  const store = new Map<string, string>()
  return {
    get length() {
      return store.size
    },
    clear: vi.fn(() => store.clear()),
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    key: vi.fn((index: number) => [...store.keys()][index] ?? null),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value)
    }),
  }
}

describe('useRuntimeSettings', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createStorageMock())
    vi.stubGlobal('sessionStorage', createStorageMock())
    window.history.replaceState(null, '', '/')
  })

  it('validates and persists backend settings', () => {
    const resetRuntimeState = vi.fn()
    const reconnectSocket = vi.fn()
    const { result } = renderHook(() =>
      useRuntimeSettings({
        defaultBaseUrl: 'http://127.0.0.1:5050',
        resetRuntimeState,
        reconnectSocket,
      }),
    )

    act(() => {
      result.current.openRuntimeSettings()
      result.current.setRuntimeSettingsForm({
        baseUrl: 'https://backend.example.test/',
        authToken: ' token-123 ',
      })
    })
    act(() => {
      result.current.submitRuntimeSettings(submitEvent())
    })

    expect(result.current.baseUrl).toBe('https://backend.example.test')
    expect(result.current.authToken).toBe('token-123')
    expect(localStorage.getItem('aidm:baseUrl')).toBe('https://backend.example.test')
    expect(sessionStorage.getItem('aidm:authToken')).toBe('token-123')
    expect(resetRuntimeState).toHaveBeenCalledOnce()
    expect(reconnectSocket).toHaveBeenCalledOnce()
    expect(result.current.runtimeSettingsOpen).toBe(false)
  })

  it('rejects non-http backend URLs', () => {
    const { result } = renderHook(() =>
      useRuntimeSettings({
        defaultBaseUrl: 'http://127.0.0.1:5050',
        resetRuntimeState: vi.fn(),
        reconnectSocket: vi.fn(),
      }),
    )

    act(() => {
      result.current.setRuntimeSettingsForm({ baseUrl: 'file:///tmp/aidm', authToken: '' })
    })
    act(() => {
      result.current.submitRuntimeSettings(submitEvent())
    })

    expect(result.current.runtimeSettingsError).toMatch(/http/)
    expect(result.current.baseUrl).toBe('http://127.0.0.1:5050')
  })

  it('allows a blank backend URL for same-origin mode', () => {
    localStorage.setItem('aidm:baseUrl', 'https://backend.example.test')
    const resetRuntimeState = vi.fn()
    const reconnectSocket = vi.fn()
    const { result } = renderHook(() =>
      useRuntimeSettings({
        defaultBaseUrl: '',
        resetRuntimeState,
        reconnectSocket,
      }),
    )

    act(() => {
      result.current.openRuntimeSettings()
      result.current.setRuntimeSettingsForm({ baseUrl: '', authToken: '' })
    })
    act(() => {
      result.current.submitRuntimeSettings(submitEvent())
    })

    expect(result.current.baseUrl).toBe('')
    expect(localStorage.getItem('aidm:baseUrl')).toBeNull()
    expect(resetRuntimeState).toHaveBeenCalledOnce()
    expect(reconnectSocket).toHaveBeenCalledOnce()
    expect(result.current.runtimeSettingsOpen).toBe(false)
  })

  it('opens a focused auth token prompt that saves same-origin credentials', () => {
    const resetRuntimeState = vi.fn()
    const reconnectSocket = vi.fn()
    const { result } = renderHook(() =>
      useRuntimeSettings({
        defaultBaseUrl: '',
        resetRuntimeState,
        reconnectSocket,
      }),
    )

    act(() => {
      result.current.openAuthTokenPrompt()
    })

    expect(result.current.runtimeSettingsOpen).toBe(true)
    expect(result.current.runtimeSettingsMode).toBe('auth')
    expect(result.current.runtimeSettingsForm.baseUrl).toBe('')

    act(() => {
      result.current.setRuntimeSettingsForm({ baseUrl: '', authToken: ' shared-token ' })
    })
    act(() => {
      result.current.submitRuntimeSettings(submitEvent())
    })

    expect(result.current.authToken).toBe('shared-token')
    expect(sessionStorage.getItem('aidm:authToken')).toBe('shared-token')
    expect(result.current.runtimeSettingsOpen).toBe(false)
    expect(result.current.runtimeSettingsMode).toBe('settings')
    expect(resetRuntimeState).toHaveBeenCalledOnce()
    expect(reconnectSocket).toHaveBeenCalledOnce()
  })

  it('loads and persists a backend URL from a share-link query parameter', () => {
    window.history.replaceState(null, '', '/?api=https%3A%2F%2Fbackend.example.test%2F')

    const { result } = renderHook(() =>
      useRuntimeSettings({
        defaultBaseUrl: 'http://127.0.0.1:5050',
        resetRuntimeState: vi.fn(),
        reconnectSocket: vi.fn(),
      }),
    )

    expect(result.current.baseUrl).toBe('https://backend.example.test')
    expect(result.current.runtimeSettingsForm.baseUrl).toBe('https://backend.example.test')
    expect(localStorage.getItem('aidm:baseUrl')).toBe('https://backend.example.test')
  })
})
