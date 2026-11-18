import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, ApiError, csrfToken } from '../lib/api'

afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'talkbuddy_csrf=; Max-Age=0' })

describe('typed API client', () => {
  it('reads only the CSRF cookie', () => {
    expect(csrfToken('other=1; talkbuddy_csrf=abc%2B123; talkbuddy_session=secret')).toBe('abc+123')
    expect(csrfToken('talkbuddy_session=secret')).toBeNull()
  })

  it('includes cookies and CSRF header on protected writes', async () => {
    document.cookie = 'talkbuddy_csrf=csrf-value'
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ save_history_enabled: true }) })
    vi.stubGlobal('fetch', fetchMock)
    await apiRequest('/api/preferences', { method: 'PATCH', body: { save_history_enabled: true } })
    const [, options] = fetchMock.mock.calls[0]
    expect((fetchMock.mock.calls[0][0] as URL).origin).toBe(window.location.origin)
    expect(options.credentials).toBe('include')
    expect(options.headers['X-CSRF-Token']).toBe('csrf-value')
    expect(options.body).toContain('save_history_enabled')
  })

  it('rejects writes without a readable CSRF cookie', async () => {
    await expect(apiRequest('/api/history', { method: 'DELETE' })).rejects.toMatchObject({ status: 403 })
  })

  it('shows the backend detail and handles network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'Not authenticated' }) }))
    await expect(apiRequest('/api/auth/me')).rejects.toThrow('Not authenticated')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
    await expect(apiRequest('/api/auth/me')).rejects.toBeInstanceOf(ApiError)
  })
})
