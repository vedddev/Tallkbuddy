import type { SocketMessage } from './types'

/** Browser-monotonic timestamps never leave the client or get compared with server clocks. */
export interface CaptureTiming {
  speechEndAtMs: number
  captureDurationMs: number
}

export interface SocketRoundTripTiming {
  submittedAtMs: number
  receivedAtMs: number
  capture?: CaptureTiming
}

export interface PhraseTimingRecord {
  id: number
  speechEndAtMs: number | null
  captureDurationMs: number | null
  speechEndToSubmitMs: number | null
  roundTripMs: number | null
  serverProcessingMs: number | null
  sttMs: number | null
  translationMs: number | null
  browserPreparationMs: number | null
  queueWaitMs: number | null
  playbackStartDelayMs: number | null
  totalMs: number | null
}

export const MAX_TIMING_RECORDS = 30

export function durationMs(start: number | null | undefined, end: number | null | undefined): number | null {
  if (start == null || end == null || !Number.isFinite(start) || !Number.isFinite(end) || end < start) return null
  return end - start
}

function validMs(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

export function timingRecord(
  id: number,
  result: Extract<SocketMessage, { type: 'result' }>,
  socket?: SocketRoundTripTiming,
): PhraseTimingRecord {
  const end = socket?.capture?.speechEndAtMs
  return {
    id,
    speechEndAtMs: end != null && Number.isFinite(end) ? end : null,
    captureDurationMs: validMs(socket?.capture?.captureDurationMs),
    speechEndToSubmitMs: durationMs(end, socket?.submittedAtMs),
    roundTripMs: durationMs(socket?.submittedAtMs, socket?.receivedAtMs),
    serverProcessingMs: validMs(result.processing_time_ms),
    sttMs: validMs(result.transcription_time_ms),
    translationMs: validMs(result.translation_time_ms),
    browserPreparationMs: null,
    queueWaitMs: null,
    playbackStartDelayMs: null,
    totalMs: null,
  }
}

export function appendTiming(records: PhraseTimingRecord[], record: PhraseTimingRecord): PhraseTimingRecord[] {
  return [...records, record].slice(-MAX_TIMING_RECORDS)
}

export function percentile(values: number[], fraction: number): number | null {
  const sorted = values.filter((value) => Number.isFinite(value) && value >= 0).sort((a, b) => a - b)
  if (!sorted.length || !Number.isFinite(fraction)) return null
  const position = (sorted.length - 1) * Math.max(0, Math.min(1, fraction))
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
}

export function latencySummary(records: PhraseTimingRecord[]) {
  const complete = records.map((record) => record.totalMs).filter((value): value is number => value !== null && Number.isFinite(value) && value >= 0)
  return {
    lastMs: records.at(-1)?.totalMs ?? null,
    completeCount: complete.length,
    averageMs: complete.length ? complete.reduce((sum, value) => sum + value, 0) / complete.length : null,
    p50Ms: percentile(complete, 0.5),
    p95Ms: percentile(complete, 0.95),
  }
}
