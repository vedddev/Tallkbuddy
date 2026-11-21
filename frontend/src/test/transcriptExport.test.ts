import { describe, expect, it } from 'vitest'
import { formatSubtitleTime, transcriptPrintHtml, transcriptSrt, transcriptTiming, transcriptTxt, type TranscriptEntry, type TranscriptSession } from '../lib/transcriptExport'

const session: TranscriptSession = { id: 'local-1', startedAt: '2026-11-21T10:00:00.000Z', sourceLanguage: 'auto', targetLanguage: 'hi' }
const phrase = (order: number, overrides: Partial<TranscriptEntry> = {}): TranscriptEntry => ({
  sessionId: session.id, order, original: 'Hello everyone', translated: 'नमस्ते सभी को',
  sourceLanguage: 'en', targetLanguage: 'hi', startMs: 1230, endMs: 2490, ...overrides,
})

describe('session transcript exports', () => {
  it('uses actual capture boundaries and marks missing timing unavailable', () => {
    expect(transcriptTiming({ phraseId: 'one', captureStartedAtMs: 100, speechStartAtMs: 250, speechEndAtMs: 780, captureDurationMs: 530 })).toEqual({ startMs: 150, endMs: 680 })
    expect(transcriptTiming(undefined)).toEqual({ startMs: null, endMs: null })
    expect(transcriptTiming({ phraseId: 'one', captureStartedAtMs: 100, speechStartAtMs: 300, speechEndAtMs: 200, captureDurationMs: 0 })).toEqual({ startMs: null, endMs: null })
    expect(formatSubtitleTime(3_661_004)).toBe('01:01:01,004')
  })

  it('formats TXT in phrase order and retains failed translations without inventing content', () => {
    const text = transcriptTxt([phrase(2, { original: 'नमस्कार', translated: null, startMs: null, endMs: null }), phrase(1)], session, 'bilingual')
    expect(text.indexOf('Hello everyone')).toBeLessThan(text.indexOf('नमस्कार'))
    expect(text).toContain('Time unavailable')
    expect(text).toContain('नमस्ते सभी को')
    expect(transcriptTxt([phrase(2, { translated: null })], session, 'translated')).toContain('Translation unavailable')
  })

  it('creates sequential Unicode SRT and omits untimed or untranslated phrases', () => {
    const result = transcriptSrt([phrase(3, { startMs: null, endMs: null }), phrase(2, { translated: 'मराठी मजकूर', startMs: 3000, endMs: 4500 }), phrase(1)], session, 'translated')
    expect(result.text).toContain('1\r\n00:00:01,230 --> 00:00:02,490\r\nनमस्ते सभी को')
    expect(result.text).toContain('2\r\n00:00:03,000 --> 00:00:04,500\r\nमराठी मजकूर')
    expect(result.skippedUntimed).toBe(1)
    expect(transcriptSrt([phrase(1, { translated: null })], session, 'translated')).toEqual({ text: '', skippedUntimed: 0, skippedNoText: 1 })
  })

  it('keeps sessions isolated and handles empty transcripts', () => {
    expect(transcriptSrt([phrase(1, { sessionId: 'other' })], session, 'original').text).toBe('')
    expect(transcriptPrintHtml([], session, 'original')).toContain('No finalized captions')
  })

  it('escapes printable PDF source, includes Devanagari fonts and keeps Unicode text', () => {
    const html = transcriptPrintHtml([phrase(1, { original: '<script>secret</script>', translated: 'नमस्ते मराठी' })], session, 'bilingual')
    expect(html).toContain('&lt;script&gt;secret&lt;/script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).toContain('नमस्ते मराठी')
    expect(html).toContain('Noto Sans Devanagari')
    expect(html).toContain('Content-Security-Policy')
  })
})
