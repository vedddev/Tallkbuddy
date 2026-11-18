import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from '../App'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.pushState({}, '', '/') })

it('redirects a signed-out visitor and opens the workspace after login', async () => {
  window.history.pushState({}, '', '/workspace')
  const user = { id: 'user-id', name: 'Taylor', email: 'taylor@example.com', is_active: true, email_verified: false, created_at: new Date().toISOString() }
  const fetchMock = vi.fn().mockImplementation(async (url: URL) => {
    if (url.pathname === '/api/auth/me') return { ok: false, status: 401, json: async () => ({ detail: 'Not authenticated' }) }
    if (url.pathname === '/api/auth/login') return { ok: true, status: 200, json: async () => user }
    if (url.pathname === '/api/auth/logout') return { ok: true, status: 200, json: async () => ({ message: 'Logged out' }) }
    if (url.pathname === '/api/preferences') return { ok: true, status: 200, json: async () => ({ source_language: 'auto', target_language: 'fr', speech_rate: 1, save_history_enabled: false }) }
    if (url.pathname === '/api/history') return { ok: true, status: 200, json: async () => ({ total: 0, items: [], limit: 5, offset: 0 }) }
    if (url.pathname === '/api/health') return { ok: true, status: 200, json: async () => ({ status: 'ok' }) }
    throw new Error(`Unexpected request: ${url.pathname}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'Good to have you back.' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'taylor@example.com' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-horse-battery-staple' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Welcome, Taylor' })).toBeInTheDocument())
  expect(fetchMock).toHaveBeenCalledWith(expect.objectContaining({ pathname: '/api/auth/login' }), expect.objectContaining({ credentials: 'include' }))
  document.cookie = 'talkbuddy_csrf=test-token'
  fireEvent.click(screen.getByRole('button', { name: 'User profile' }))
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(screen.getByRole('heading', { name: /A conversation without borders/i })).toBeInTheDocument())
})
