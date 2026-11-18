import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { TranslatePage } from '../pages/TranslatePage'
import { api } from '../lib/api'
import * as speech from '../lib/speech'

const preferences = { source_language: 'en' as const, target_language: 'hi' as const, speech_rate: 1.2, save_history_enabled: false }
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('translates into the selected language, copies, speaks, and swaps a completed result', async () => {
  vi.spyOn(api, 'preferences').mockResolvedValue(preferences)
  const translate = vi.spyOn(api, 'translateText').mockResolvedValue({ original_text: 'Good morning', translated_text: 'おはようございます', target_language: 'ja' })
  const speak = vi.spyOn(speech, 'speak').mockImplementation(() => undefined)
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  render(<MemoryRouter><TranslatePage /></MemoryRouter>)
  await waitFor(() => expect(screen.getByLabelText('Source language')).toHaveValue('en'))
  expect(screen.getByText('Ready to translate')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Target language'), { target: { value: 'ja' } })
  fireEvent.change(screen.getByLabelText('Text to translate'), { target: { value: 'Good morning' } })
  fireEvent.click(screen.getByRole('button', { name: 'Translate text' }))
  await waitFor(() => expect(screen.getByText('おはようございます')).toBeInTheDocument())
  expect(translate).toHaveBeenCalledWith('Good morning', 'ja', undefined)
  fireEvent.click(screen.getByRole('button', { name: 'Copy translation' }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('おはようございます'))
  fireEvent.click(screen.getByRole('button', { name: 'Speak translation' }))
  expect(speak).toHaveBeenCalledWith('おはようございます', 'ja', 1.2)
  fireEvent.click(screen.getByRole('button', { name: 'Swap languages' }))
  expect(screen.getByLabelText('Source language')).toHaveValue('ja')
  expect(screen.getByLabelText('Target language')).toHaveValue('en')
  expect(screen.getByLabelText('Text to translate')).toHaveValue('おはようございます')
  expect(screen.getByText('Ready to translate')).toBeInTheDocument()
})

it('requires explicit history opt-in and closes the saved session', async () => {
  vi.spyOn(api, 'preferences').mockResolvedValue({ ...preferences, save_history_enabled: true })
  const createSession = vi.spyOn(api, 'createSession').mockResolvedValue({ id: 'session-1', title: null, source_language: 'en', target_language: 'hi', started_at: new Date().toISOString(), ended_at: null })
  const translate = vi.spyOn(api, 'translateText').mockResolvedValue({ original_text: 'Hello', translated_text: 'नमस्ते', target_language: 'hi', saved: true })
  const endSession = vi.spyOn(api, 'endSession').mockResolvedValue({ id: 'session-1', title: null, source_language: 'en', target_language: 'hi', started_at: new Date().toISOString(), ended_at: new Date().toISOString() })
  render(<MemoryRouter><TranslatePage /></MemoryRouter>)
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Save this translation' })).toBeEnabled())
  fireEvent.click(screen.getByRole('checkbox', { name: 'Save this translation' }))
  fireEvent.change(screen.getByLabelText('Text to translate'), { target: { value: 'Hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Translate text' }))
  await waitFor(() => expect(screen.getByText('Saved to history')).toBeInTheDocument())
  expect(createSession).toHaveBeenCalledWith('en', 'hi')
  expect(translate).toHaveBeenCalledWith('Hello', 'hi', 'session-1')
  expect(endSession).toHaveBeenCalledWith('session-1')
})

it('shows a loading state and an actionable error without stale output', async () => {
  vi.spyOn(api, 'preferences').mockResolvedValue(preferences)
  let reject!: (error: Error) => void
  vi.spyOn(api, 'translateText').mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
  render(<MemoryRouter><TranslatePage /></MemoryRouter>)
  await waitFor(() => expect(screen.getByLabelText('Source language')).toHaveValue('en'))
  fireEvent.change(screen.getByLabelText('Text to translate'), { target: { value: 'Hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Translate text' }))
  expect(screen.getByText('Translating…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Translate text/ })).toBeDisabled()
  reject(new Error('AI service failed'))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('AI service failed'))
  expect(screen.getByText('Ready to translate')).toBeInTheDocument()
})
