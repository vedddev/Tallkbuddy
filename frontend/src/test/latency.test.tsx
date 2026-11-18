import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { LatencyDiagnostics } from '../components/LatencyDiagnostics'
import { appendTiming, durationMs, latencySummary, percentile, timingRecord, type PhraseTimingRecord } from '../lib/latency'
import type { SocketMessage } from '../lib/types'

const result: Extract<SocketMessage, { type: 'result' }> = {
  type: 'result', chunk_id: 1, original: 'Hello', translated: 'Bonjour',
  target_language: 'fr', detected_language: 'en', processing_time_ms: 800,
  transcription_time_ms: 500, translation_time_ms: 250,
}

it('keeps browser durations separate from server-provided stages', () => {
  const record = timingRecord(1, result, {
    capture: { speechEndAtMs: 100, captureDurationMs: 1200 },
    submittedAtMs: 820, receivedAtMs: 1700,
  })
  expect(record).toMatchObject({
    captureDurationMs: 1200, speechEndToSubmitMs: 720, roundTripMs: 880,
    serverProcessingMs: 800, sttMs: 500, translationMs: 250, totalMs: null,
  })
  expect(durationMs(record.speechEndAtMs, 1900)).toBe(1800)
  expect(durationMs(300, 100)).toBeNull()
})

it('treats missing or invalid optional timing as unavailable, never zero', () => {
  const record = timingRecord(1, { ...result, transcription_time_ms: undefined, translation_time_ms: -1 }, undefined)
  expect(record.sttMs).toBeNull()
  expect(record.translationMs).toBeNull()
  expect(record.roundTripMs).toBeNull()
  expect(record.totalMs).toBeNull()
})

it('calculates interpolated p50 and p95 only from completed playback records', () => {
  const base = timingRecord(1, result)
  const records: PhraseTimingRecord[] = [100, 200, 300, 400].map((totalMs, id) => ({ ...base, id, totalMs }))
  records.push({ ...base, id: 5, totalMs: null })
  const summary = latencySummary(records)
  expect(summary.averageMs).toBe(250)
  expect(summary.p50Ms).toBe(250)
  expect(summary.p95Ms).toBeCloseTo(385)
  expect(summary.lastMs).toBeNull()
  expect(percentile([], 0.95)).toBeNull()
  expect(latencySummary([])).toEqual({ lastMs: null, completeCount: 0, averageMs: null, p50Ms: null, p95Ms: null })
})

it('bounds in-memory records and renders an honest empty/reset state', () => {
  const base = timingRecord(1, result)
  let records = [base]
  for (let id = 2; id <= 50; id++) records = appendTiming(records, { ...base, id })
  expect(records).toHaveLength(30)
  expect(records[0].id).toBe(21)
  const reset = vi.fn()
  const view = render(<LatencyDiagnostics records={[]} connection="Offline" onReset={reset} />)
  fireEvent.click(screen.getByText(/Diagnostics/))
  expect(screen.getByText(/No phrase timings yet/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled()
  view.rerender(<LatencyDiagnostics records={records} connection="Listening" onReset={reset} />)
  expect(screen.getByText(/30 recent phrases/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
  expect(reset).toHaveBeenCalledOnce()
})
