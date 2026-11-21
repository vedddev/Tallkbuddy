import type { CaptureTiming } from './latency'

export type TranscriptSelection = 'original' | 'translated' | 'bilingual'

export interface TranscriptSession {
  id: string
  startedAt: string
  sourceLanguage: string
  targetLanguage: string
}

export interface TranscriptEntry {
  sessionId: string
  order: number
  original: string
  translated: string | null
  sourceLanguage: string | null
  targetLanguage: string
  startMs: number | null
  endMs: number | null
}

export const MAX_TRANSCRIPT_ENTRIES = 1000

/** Convert browser-monotonic VAD boundaries to offsets from capture start. */
export function transcriptTiming(capture?: CaptureTiming): Pick<TranscriptEntry, 'startMs' | 'endMs'> {
  const base = capture?.captureStartedAtMs
  const start = capture?.speechStartAtMs
  const end = capture?.speechEndAtMs
  if (base == null || start == null || end == null ||
      ![base, start, end].every(Number.isFinite) || start < base || end <= start) {
    return { startMs: null, endMs: null }
  }
  const startMs = Math.round(start - base)
  const endMs = Math.round(end - base)
  return endMs > startMs ? { startMs, endMs } : { startMs: null, endMs: null }
}

export function formatSubtitleTime(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) throw new Error('Invalid subtitle time')
  const total = Math.floor(milliseconds)
  const hours = Math.floor(total / 3_600_000)
  const minutes = Math.floor(total / 60_000) % 60
  const seconds = Math.floor(total / 1000) % 60
  const ms = total % 1000
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}

function phraseText(entry: TranscriptEntry, selection: TranscriptSelection): string | null {
  if (selection === 'original') return entry.original.trim() || null
  if (selection === 'translated') return entry.translated?.trim() || null
  return [entry.original.trim(), entry.translated?.trim()].filter(Boolean).join('\n') || null
}

function ordered(entries: TranscriptEntry[], session: TranscriptSession): TranscriptEntry[] {
  return entries.filter((entry) => entry.sessionId === session.id)
    .sort((a, b) => a.order - b.order)
}

function languageLabel(code: string): string { return code === 'auto' ? 'Auto-detect' : code }

function range(entry: TranscriptEntry): string {
  return entry.startMs === null || entry.endMs === null
    ? 'Time unavailable'
    : `${formatSubtitleTime(entry.startMs)} – ${formatSubtitleTime(entry.endMs)}`
}

export function transcriptTxt(entries: TranscriptEntry[], session: TranscriptSession, selection: TranscriptSelection): string {
  const header = [
    'TalkBuddy transcript', `Session: ${session.id}`, `Date: ${session.startedAt}`,
    `Source: ${languageLabel(session.sourceLanguage)}`, `Target: ${session.targetLanguage}`,
    `Content: ${selection}`, '',
  ]
  const lines = ordered(entries, session).flatMap((entry) => {
    const text = phraseText(entry, selection)
    if (!text) return selection === 'translated'
      ? [`${entry.order}. [${range(entry)}] Translation unavailable`, ''] : []
    return [`${entry.order}. [${range(entry)}] Source: ${entry.sourceLanguage || 'Unknown'} → ${entry.targetLanguage}`, text, '']
  })
  return [...header, ...(lines.length ? lines : ['No finalized captions.'])].join('\n').trimEnd() + '\n'
}

export interface SrtResult { text: string; skippedUntimed: number; skippedNoText: number }

export function transcriptSrt(entries: TranscriptEntry[], session: TranscriptSession, selection: TranscriptSelection): SrtResult {
  const blocks: string[] = []
  let skippedUntimed = 0
  let skippedNoText = 0
  for (const entry of ordered(entries, session)) {
    const text = phraseText(entry, selection)
    if (!text) { skippedNoText++; continue }
    if (entry.startMs === null || entry.endMs === null || !Number.isFinite(entry.startMs) || !Number.isFinite(entry.endMs) || entry.startMs < 0 || entry.endMs <= entry.startMs) {
      skippedUntimed++
      continue
    }
    blocks.push(`${blocks.length + 1}\r\n${formatSubtitleTime(entry.startMs)} --> ${formatSubtitleTime(entry.endMs)}\r\n${text.replace(/\r\n?|\n/g, '\r\n')}`)
  }
  return { text: blocks.length ? blocks.join('\r\n\r\n') + '\r\n' : '', skippedUntimed, skippedNoText }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!)
}

/** Printable HTML lets the browser shape Devanagari with compatible system fonts. */
export function transcriptPrintHtml(entries: TranscriptEntry[], session: TranscriptSession, selection: TranscriptSelection): string {
  const phrases = ordered(entries, session).map((entry) => {
    const text = phraseText(entry, selection)
    const body = text || (selection === 'translated' ? 'Translation unavailable' : '')
    if (!body) return ''
    return `<article><p class="meta">${entry.order}. ${escapeHtml(range(entry))} · ${escapeHtml(entry.sourceLanguage || 'Unknown')} → ${escapeHtml(entry.targetLanguage)}</p><p lang="${escapeHtml(selection === 'translated' ? entry.targetLanguage : entry.sourceLanguage || '')}">${escapeHtml(body)}</p></article>`
  }).join('')
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>TalkBuddy transcript</title><style>
    @page{size:A4;margin:18mm}body{font-family:Inter,"Noto Sans Devanagari","Nirmala UI",Mangal,"Lohit Devanagari",sans-serif;color:#17171d;font-size:11pt;line-height:1.5}
    h1{font-size:18pt;margin:0 0 8mm}.summary{font-size:9pt;color:#555;margin-bottom:8mm}article{break-inside:avoid;margin:0 0 6mm}article p{white-space:pre-wrap;overflow-wrap:anywhere;margin:2mm 0}.meta{font-size:8pt;color:#666}
    </style></head><body><h1>TalkBuddy transcript</h1><div class="summary">Session: ${escapeHtml(session.id)}<br>Date: ${escapeHtml(session.startedAt)}<br>Source: ${escapeHtml(languageLabel(session.sourceLanguage))} · Target: ${escapeHtml(session.targetLanguage)} · Content: ${escapeHtml(selection)}</div>${phrases || '<p>No finalized captions.</p>'}</body></html>`
}

export function transcriptFileName(session: TranscriptSession, extension: 'txt' | 'srt'): string {
  const date = /^\d{4}-\d{2}-\d{2}/.exec(session.startedAt)?.[0] || 'session'
  const id = session.id.replace(/[^a-zA-Z0-9-]/g, '').slice(0, 36) || 'local'
  return `talkbuddy-${date}-${id}.${extension}`
}
