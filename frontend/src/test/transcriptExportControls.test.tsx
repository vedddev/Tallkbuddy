import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TranscriptExportControls } from '../components/TranscriptExportControls'
import type { TranscriptEntry, TranscriptSession } from '../lib/transcriptExport'

afterEach(() => vi.restoreAllMocks())

const session: TranscriptSession = { id: 'local-1', startedAt: '2026-11-21T10:00:00Z', sourceLanguage: 'en', targetLanguage: 'mr' }
const entry: TranscriptEntry = { sessionId: session.id, order: 1, original: 'Hello', translated: 'नमस्कार', sourceLanguage: 'en', targetLanguage: 'mr', startMs: null, endMs: null }

it('keeps empty exports disabled and reports omitted untimed SRT phrases', () => {
  const { rerender } = render(<TranscriptExportControls session={session} entries={[]} truncated={0} />)
  expect(screen.getByRole('button', { name: 'Download TXT' })).toBeDisabled()
  rerender(<TranscriptExportControls session={session} entries={[entry]} truncated={0} />)
  expect(screen.getByText(/SRT requires real speech/)).toHaveTextContent('1 untimed')
  fireEvent.click(screen.getByRole('button', { name: 'Download SRT' }))
  expect(screen.getByRole('status')).toHaveTextContent('No timed captions')
})

it('opens a local printable Unicode transcript without backend calls', () => {
  const write = vi.fn()
  const print = vi.fn()
  const popup = { document: { open: vi.fn(), write, close: vi.fn(), fonts: { ready: Promise.resolve() } }, focus: vi.fn(), print, closed: false, opener: null }
  vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
  render(<TranscriptExportControls session={session} entries={[entry]} truncated={0} />)
  fireEvent.click(screen.getByRole('button', { name: 'Print / Save PDF' }))
  expect(write).toHaveBeenCalledWith(expect.stringContaining('नमस्कार'))
  expect(screen.getByRole('status')).toHaveTextContent('Save as PDF')
})
