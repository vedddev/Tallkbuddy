import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { SettingsPage } from '../pages/SettingsPage'
import { AuthProvider } from '../contexts/AuthContext'
import { ThemeProvider } from '../contexts/ThemeContext'
import { api } from '../lib/api'

const user = { id: 'user-1', name: 'Taylor', email: 'taylor@example.com', is_active: true, email_verified: false, created_at: new Date().toISOString() }
const preferences = { source_language: 'auto' as const, target_language: 'hi' as const, speech_rate: 1, save_history_enabled: false }
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); document.documentElement.classList.remove('dark') })

function renderPage() { render(<ThemeProvider><MemoryRouter><AuthProvider><SettingsPage /></AuthProvider></MemoryRouter></ThemeProvider>) }

it('persists language, speech rate, and history preferences through the existing API', async () => {
  vi.spyOn(api, 'me').mockResolvedValue(user)
  vi.spyOn(api, 'preferences').mockResolvedValue(preferences)
  const update = vi.spyOn(api, 'updatePreferences').mockImplementation(async (value) => ({ ...preferences, ...value }))
  renderPage()
  await waitFor(() => expect(screen.getByLabelText('Default target')).toHaveValue('hi'))
  fireEvent.change(screen.getByLabelText('Default source'), { target: { value: 'en' } })
  fireEvent.change(screen.getByLabelText('Default target'), { target: { value: 'ja' } })
  fireEvent.change(screen.getByLabelText('Speech speed'), { target: { value: '1.5' } })
  fireEvent.click(screen.getByRole('checkbox', { name: /Allow history saving/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(update).toHaveBeenCalledWith({ source_language: 'en', target_language: 'ja', speech_rate: 1.5, save_history_enabled: true }))
  expect(screen.getByRole('status', { name: 'Saved' })).toBeInTheDocument()
})

it('switches theme locally and displays the authenticated account', async () => {
  vi.spyOn(api, 'me').mockResolvedValue(user)
  vi.spyOn(api, 'preferences').mockResolvedValue(preferences)
  renderPage()
  expect(await screen.findByText('taylor@example.com')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Light' }))
  expect(localStorage.getItem('talkbuddy-theme')).toBe('light')
  expect(screen.getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'true')
})

it('shows settings load and save errors', async () => {
  vi.spyOn(api, 'me').mockResolvedValue(user)
  vi.spyOn(api, 'preferences').mockResolvedValue(preferences)
  vi.spyOn(api, 'updatePreferences').mockRejectedValue(new Error('Could not save preferences'))
  renderPage()
  expect(screen.getByText('Loading settings…')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save preferences')
})

it('retries a failed preferences load and signs out through the account action', async () => {
  vi.spyOn(api, 'me').mockResolvedValue(user)
  const load = vi.spyOn(api, 'preferences').mockRejectedValueOnce(new Error('Settings unavailable')).mockResolvedValue(preferences)
  const logout = vi.spyOn(api, 'logout').mockResolvedValue({ message: 'Logged out' })
  renderPage()
  expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(screen.getByLabelText('Default target')).toHaveValue('hi'))
  expect(load).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(logout).toHaveBeenCalledOnce())
})
