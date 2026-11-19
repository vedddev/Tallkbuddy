import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { App } from '../App'
import * as meetingAudio from '../lib/meetingAudio'
import { TranslationSocket } from '../lib/socket'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.pushState({}, '', '/') })

function mockAuthenticatedApp() {
  const user = { id: 'test-user', name: 'Taylor', email: 'taylor@example.com', is_active: true, email_verified: false, created_at: new Date().toISOString() }
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: URL) => ({
    ok: true, status: 200, json: async () => url.pathname === '/api/auth/me'
      ? user : { source_language: 'auto', target_language: 'hi', speech_rate: 1, save_history_enabled: false },
  })))
}

it('opens the dedicated meeting route from the legacy hash and stops capture on navigation', async () => {
  window.history.pushState({}, '', '/workspace#meeting')
  mockAuthenticatedApp()
  const capture = { pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined), setOriginalMuted: vi.fn().mockResolvedValue(true), originalMuteSupported: true }
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockResolvedValue(capture)
  vi.spyOn(TranslationSocket.prototype, 'connect').mockResolvedValue(undefined)
  const close = vi.spyOn(TranslationSocket.prototype, 'close').mockImplementation(() => undefined)
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'Meeting Interpreter' })).toBeInTheDocument()
  expect(window.location.pathname).toBe('/meeting')
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('link', { name: 'Translate' }))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Text Translation' })).toBeInTheDocument())
  expect(window.location.pathname).toBe('/translate')
  await waitFor(() => expect(capture.stop).toHaveBeenCalledOnce())
  expect(close).toHaveBeenCalled()
})

it('redirects the legacy translation hash to the dedicated text page', async () => {
  window.history.pushState({}, '', '/workspace#translate')
  mockAuthenticatedApp()
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'Text Translation' })).toBeInTheDocument()
  expect(window.location.pathname).toBe('/translate')
  expect(screen.getByRole('link', { name: 'Translate' })).toHaveAttribute('aria-current', 'page')
})

it('releases microphone capture when switching to the meeting listener', async () => {
  window.history.pushState({}, '', '/microphone')
  mockAuthenticatedApp()
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { enumerateDevices: vi.fn().mockResolvedValue([]) } })
  const capture = { pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined), setOriginalMuted: vi.fn().mockResolvedValue(false), originalMuteSupported: false }
  vi.spyOn(meetingAudio, 'startMicrophoneCapture').mockResolvedValue(capture)
  vi.spyOn(TranslationSocket.prototype, 'connect').mockResolvedValue(undefined)
  vi.spyOn(TranslationSocket.prototype, 'close').mockImplementation(() => undefined)
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'Microphone Translator' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('link', { name: 'Meeting Listener' }))
  expect(await screen.findByRole('heading', { name: 'Meeting Interpreter' })).toBeInTheDocument()
  await waitFor(() => expect(capture.stop).toHaveBeenCalledOnce())
})
