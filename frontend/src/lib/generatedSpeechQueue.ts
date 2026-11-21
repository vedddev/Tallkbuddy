import type { PlaybackStatus } from './speechQueue'

const MAX_AUDIO_BYTES = 2 * 1024 * 1024

/** Validate the server's bounded 24 kHz mono PCM WAV before local playback. */
export function decodeSpeechWav(encoded: string): Blob {
  if (encoded.length > Math.ceil(MAX_AUDIO_BYTES * 4 / 3) + 8) throw new Error('Generated speech is too large.')
  let binary: string
  try { binary = atob(encoded) } catch { throw new Error('Generated speech is invalid.') }
  if (binary.length < 44 || binary.length > MAX_AUDIO_BYTES) throw new Error('Generated speech is invalid.')
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
  const view = new DataView(bytes.buffer)
  const tag = (offset: number) => String.fromCharCode(...bytes.subarray(offset, offset + 4))
  if (tag(0) !== 'RIFF' || tag(8) !== 'WAVE' || view.getUint32(4, true) + 8 !== bytes.length) throw new Error('Generated speech is not a complete WAV file.')
  let format = false
  let audio = false
  for (let offset = 12; offset + 8 <= bytes.length;) {
    const size = view.getUint32(offset + 4, true)
    const end = offset + 8 + size
    if (end > bytes.length) throw new Error('Generated speech WAV is incomplete.')
    if (tag(offset) === 'fmt ') {
      if (size < 16 || view.getUint16(offset + 8, true) !== 1 || view.getUint16(offset + 10, true) !== 1 || view.getUint32(offset + 12, true) !== 24_000 || view.getUint32(offset + 16, true) !== 48_000 || view.getUint16(offset + 20, true) !== 2 || view.getUint16(offset + 22, true) !== 16) throw new Error('Generated speech format is unsupported.')
      format = true
    }
    if (tag(offset) === 'data') { if (!size || size % 2 || size > 24_000 * 2 * 30) throw new Error('Generated speech duration is invalid.'); audio = true }
    offset = end + (size & 1)
  }
  if (!format || !audio) throw new Error('Generated speech WAV is incomplete.')
  return new Blob([bytes], { type: 'audio/wav' })
}

/** One active audio element, bounded pending items, and URL cleanup on every path. */
export class GeneratedSpeechQueue {
  private pending: { id: number; blob: Blob; queuedAtMs: number }[] = []
  private active: HTMLAudioElement | null = null
  private activeStarted = false
  private activeUrl: string | null = null
  private activeId: number | null = null
  private seen = new Set<number>()
  private paused = false

  constructor(
    private onStatus: (status: PlaybackStatus, pending: number) => void = () => undefined,
    private onError: (message: string) => void = () => undefined,
    private onStarted: (id: number, startedAtMs: number, queueWaitMs: number, playbackStartDelayMs: number) => void = () => undefined,
    private onSettled: (id: number, started: boolean, failed: boolean) => void = () => undefined,
  ) {}

  enqueue(id: number, encoded: string): boolean {
    if (this.seen.has(id)) return true
    if (this.pending.length >= 8) return false
    const blob = decodeSpeechWav(encoded)
    this.seen.add(id)
    if (this.seen.size > 1024) this.seen.delete(this.seen.values().next().value!)
    this.pending.push({ id, blob, queuedAtMs: performance.now() })
    this.next()
    this.report()
    return true
  }

  pause(): void { this.paused = true; this.active?.pause(); this.report() }
  resume(): void {
    this.paused = false
    if (this.active) {
      const audio = this.active
      try { void audio.play().catch(() => { if (this.active === audio) this.fail('Browser blocked translated audio. Interact with the page and resume playback.') }) }
      catch { if (this.active === audio) this.fail('Browser blocked translated audio. Interact with the page and resume playback.') }
    }
    else this.next()
    this.report()
  }
  stop(): void {
    this.paused = true
    this.pending = []
    this.seen.clear()
    this.release()
    this.report()
  }

  private release(): void {
    if (this.active) { this.active.onended = null; this.active.onerror = null; this.active.onplaying = null; this.active.pause(); this.active.removeAttribute('src'); this.active.load(); this.active = null }
    this.activeStarted = false
    this.activeId = null
    if (this.activeUrl) { URL.revokeObjectURL(this.activeUrl); this.activeUrl = null }
  }
  private fail(message: string): void { const id = this.activeId; const started = this.activeStarted; this.onError(message); this.release(); if (id !== null) this.onSettled(id, started, true); this.next(); this.report() }
  private next(): void {
    if (this.paused || this.active || !this.pending.length) return
    const item = this.pending.shift()!
    const url = URL.createObjectURL(item.blob)
    let audio: HTMLAudioElement
    try { audio = new Audio(url) }
    catch { URL.revokeObjectURL(url); this.onError('Generated speech could not be played. Captions will continue.'); this.onSettled(item.id, false, true); this.next(); return }
    this.active = audio
    this.activeId = item.id
    this.activeUrl = url
    const playCalledAtMs = performance.now()
    audio.onplaying = () => {
      if (this.active !== audio) return
      audio.onplaying = null
      this.activeStarted = true
      const startedAtMs = performance.now()
      this.onStarted(item.id, startedAtMs, Math.max(0, playCalledAtMs - item.queuedAtMs), Math.max(0, startedAtMs - playCalledAtMs))
      this.report()
    }
    audio.onended = () => { this.release(); this.onSettled(item.id, true, false); this.next(); this.report() }
    audio.onerror = () => this.fail('Generated speech could not be played. Captions will continue.')
    try { void audio.play().catch(() => { if (this.active === audio) this.fail('Browser blocked translated audio. Interact with the page and retry.') }) }
    catch { if (this.active === audio) this.fail('Browser blocked translated audio. Interact with the page and retry.') }
    this.report()
  }
  private report(): void { this.onStatus(this.paused ? 'paused' : this.active && this.activeStarted ? 'playing' : 'idle', this.pending.length) }
}
