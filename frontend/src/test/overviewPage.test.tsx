import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { OverviewPage } from '../pages/OverviewPage'
import { AuthProvider } from '../contexts/AuthContext'
import { api } from '../lib/api'

afterEach(() => vi.restoreAllMocks())

function renderPage() { render(<MemoryRouter><AuthProvider><OverviewPage /></AuthProvider></MemoryRouter>) }

it('shows real API reachability and an empty private history state', async () => {
  vi.spyOn(api, 'me').mockResolvedValue({ id: 'user-1', name: 'Taylor Park', email: 'taylor@example.com', is_active: true, email_verified: false, created_at: new Date().toISOString() })
  vi.spyOn(api, 'history').mockResolvedValue({ items: [], total: 0, offset: 0, limit: 5 })
  vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok' })
  renderPage()
  expect(await screen.findByRole('heading', { name: 'Welcome, Taylor' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Start Live Meeting/ })).toHaveAttribute('href', '/meeting')
  expect(screen.getByRole('link', { name: /Open Text Translation/ })).toHaveAttribute('href', '/translate')
  expect(await screen.findByText('No saved sessions')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'API reachable' })).toBeInTheDocument()
})

it('shows recent sessions returned by the API and reports unavailable services accurately', async () => {
  vi.spyOn(api, 'me').mockResolvedValue({ id: 'user-1', name: 'Taylor', email: 'taylor@example.com', is_active: true, email_verified: false, created_at: new Date().toISOString() })
  vi.spyOn(api, 'history').mockResolvedValue({ items: [{ id: 'session-1', title: 'Project review', source_language: 'en', target_language: 'hi', started_at: new Date().toISOString(), ended_at: null }], total: 1, offset: 0, limit: 5 })
  vi.spyOn(api, 'health').mockRejectedValue(new Error('Offline'))
  renderPage()
  expect(await screen.findByRole('link', { name: /Project review/ })).toHaveAttribute('href', '/history/session-1')
  await waitFor(() => expect(screen.getByRole('status', { name: 'API unavailable' })).toBeInTheDocument())
})
