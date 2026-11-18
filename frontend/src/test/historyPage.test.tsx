import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { HistoryPage, SessionDetailPage } from '../pages/HistoryPage'
import { api } from '../lib/api'
import type { TranslationSession } from '../lib/types'

const sessions: TranslationSession[] = [
  { id: 'one', title: 'Morning standup', source_language: 'en', target_language: 'hi', started_at: '2026-11-16T09:00:00Z', ended_at: null },
  { id: 'two', title: 'Design review', source_language: 'ja', target_language: 'ko', started_at: '2026-11-15T09:00:00Z', ended_at: null },
]
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('searches and filters only the loaded history page', async () => {
  vi.spyOn(api, 'history').mockResolvedValue({ items: sessions, total: 2, offset: 0, limit: 20 })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: /Morning standup/ })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Design review/ })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search this page'), { target: { value: 'design' } })
  expect(screen.queryByRole('link', { name: /Morning standup/ })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Target language'), { target: { value: 'hi' } })
  expect(screen.getByText('No matches on this page')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search this page'), { target: { value: '' } })
  expect(screen.getByRole('link', { name: /Morning standup/ })).toBeInTheDocument()
})

it('supports server pagination and shows a true empty state', async () => {
  const history = vi.spyOn(api, 'history').mockImplementation(async (offset) => offset === 0
    ? { items: sessions, total: 22, offset: 0, limit: 20 }
    : { items: [{ ...sessions[0], id: 'last', title: 'Last session' }], total: 22, offset: 20, limit: 20 })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(await screen.findByRole('button', { name: 'Next page' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
  expect(await screen.findByRole('link', { name: /Last session/ })).toBeInTheDocument()
  expect(history).toHaveBeenCalledWith(20, 20)
})

it('renders loading, empty, and error states without fake sessions', async () => {
  let resolve!: (value: { items: TranslationSession[]; total: number; offset: number; limit: number }) => void
  vi.spyOn(api, 'history').mockReturnValue(new Promise((done) => { resolve = done }))
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading saved sessions…')).toBeInTheDocument()
  resolve({ items: [], total: 0, offset: 0, limit: 20 })
  expect(await screen.findByText('No saved sessions')).toBeInTheDocument()
})

it('reports history loading errors and offers retry', async () => {
  vi.spyOn(api, 'history').mockRejectedValue(new Error('History unavailable'))
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('History unavailable')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

it('clears history only after confirmation and refreshes the list', async () => {
  vi.spyOn(api, 'history').mockResolvedValueOnce({ items: sessions, total: 2, offset: 0, limit: 20 }).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 20 })
  const clear = vi.spyOn(api, 'clearHistory').mockResolvedValue({ deleted_sessions: 2 })
  vi.stubGlobal('confirm', vi.fn(() => true))
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Clear history' }))
  await waitFor(() => expect(clear).toHaveBeenCalledOnce())
  expect(await screen.findByText('No saved sessions')).toBeInTheDocument()
})

it('shows saved message details and protects deletion with confirmation', async () => {
  vi.spyOn(api, 'session').mockResolvedValue({ session: sessions[0], messages: { total: 1, offset: 0, limit: 50, items: [{ id: 'message-1', original_text: 'Good morning', translated_text: 'सुप्रभात', detected_language: 'en', created_at: '2026-11-16T09:01:00Z' }] } })
  vi.spyOn(api, 'preferences').mockResolvedValue({ source_language: 'auto', target_language: 'hi', speech_rate: 1, save_history_enabled: true })
  const remove = vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined)
  vi.stubGlobal('confirm', vi.fn(() => false))
  render(<MemoryRouter initialEntries={['/history/one']}><Routes><Route path="/history/:sessionId" element={<SessionDetailPage />} /><Route path="/history" element={<p>History list</p>} /></Routes></MemoryRouter>)
  expect(await screen.findByText('सुप्रभात')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Delete session' }))
  expect(remove).not.toHaveBeenCalled()
  vi.stubGlobal('confirm', vi.fn(() => true))
  fireEvent.click(screen.getByRole('button', { name: 'Delete session' }))
  await waitFor(() => expect(remove).toHaveBeenCalledWith('one'))
})
