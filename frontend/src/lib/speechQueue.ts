import type { Language } from './types'
import { languageByCode } from './languageRegistry'
import { voiceForLanguage } from './voices'

export type EnqueueStatus = 'queued' | 'duplicate' | 'queue_full' | 'voice_unavailable' | 'empty'
export type PlaybackStatus = 'idle' | 'playing' | 'paused'
export type PlaybackTimingEvent =
  | { type: 'prepared'; chunkId: number; preparationMs: number }
  | { type: 'started'; chunkId: number; queueWaitMs: number; playbackStartDelayMs: number; startedAtMs: number }

/** Plays completed translations in arrival order without overlapping speech. */
export class SpeechQueue {
  private pending: SpeechSynthesisUtterance[] = []
  private active: SpeechSynthesisUtterance | null = null
  private activeStarted = false
  private seen = new Set<number>()
  private utteranceLanguages = new WeakMap<SpeechSynthesisUtterance, Language>()
  private utteranceTiming = new WeakMap<SpeechSynthesisUtterance, { chunkId: number; queuedAtMs: number; speakCalledAtMs: number | null }>()
  private paused = false

  constructor(
    private synth: SpeechSynthesis = window.speechSynthesis,
    private onPlaybackError: (language: Language) => void = () => undefined,
    private onStatusChange: (status: PlaybackStatus, queued: number) => void = () => undefined,
    private onTiming: (event: PlaybackTimingEvent) => void = () => undefined,
    private onSettled: (chunkId: number, started: boolean, failed: boolean) => void = () => undefined,
  ) {}

  enqueue(chunkId: number, text: string, language: Language, rate: number): EnqueueStatus {
    const preparationStartedAtMs = performance.now()
    if (!text.trim()) return 'empty'
    if (this.seen.has(chunkId)) return 'duplicate'
    if (this.pending.length >= 8) return 'queue_full'
    const voice = voiceForLanguage(this.synth.getVoices(), language)
    if (!voice) return 'voice_unavailable'
    if (this.seen.size >= 1024) this.seen.delete(this.seen.values().next().value!)
    this.seen.add(chunkId)
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = languageByCode(language).speech_tag
    utterance.voice = voice
    utterance.rate = rate
    this.utteranceLanguages.set(utterance, language)
    utterance.onstart = () => {
      const timing = this.utteranceTiming.get(utterance)
      if (!timing || this.active !== utterance || timing.speakCalledAtMs === null) return
      utterance.onstart = null
      this.activeStarted = true
      const startedAtMs = performance.now()
      this.onTiming({
        type: 'started', chunkId: timing.chunkId,
        queueWaitMs: Math.max(0, timing.speakCalledAtMs - timing.queuedAtMs),
        playbackStartDelayMs: Math.max(0, startedAtMs - timing.speakCalledAtMs),
        startedAtMs,
      })
      this.reportStatus()
    }
    utterance.onend = () => this.complete(utterance, false)
    utterance.onerror = () => { this.onPlaybackError(language); this.complete(utterance, true) }
    const queuedAtMs = performance.now()
    this.utteranceTiming.set(utterance, { chunkId, queuedAtMs, speakCalledAtMs: null })
    this.pending.push(utterance)
    this.onTiming({ type: 'prepared', chunkId, preparationMs: Math.max(0, queuedAtMs - preparationStartedAtMs) })
    this.playNext()
    this.reportStatus()
    return 'queued'
  }

  pause(): void { this.paused = true; this.synth.pause(); this.reportStatus() }

  resume(): void { this.paused = false; this.synth.resume(); this.playNext(); this.reportStatus() }

  stop(): void {
    this.paused = true
    this.pending = []
    this.seen.clear()
    if (this.active) { this.active.onstart = null; this.active.onend = null; this.active.onerror = null }
    this.active = null
    this.activeStarted = false
    this.synth.cancel()
    this.reportStatus()
  }

  private complete(utterance: SpeechSynthesisUtterance, failed: boolean): void {
    if (this.active !== utterance) return
    const id = this.utteranceTiming.get(utterance)?.chunkId
    const started = this.activeStarted
    this.active = null
    this.activeStarted = false
    if (id !== undefined) this.onSettled(id, started, failed)
    this.playNext()
    this.reportStatus()
  }

  private reportStatus(): void {
    this.onStatusChange(!this.active && !this.pending.length ? 'idle' : this.paused ? 'paused' : this.active && this.activeStarted ? 'playing' : 'idle', this.pending.length)
  }

  private playNext(): void {
    if (this.paused || this.active || !this.pending.length) return
    const next = this.pending.shift()!
    this.active = next
    this.activeStarted = false
    const timing = this.utteranceTiming.get(next)
    if (timing) timing.speakCalledAtMs = performance.now()
    try { this.synth.speak(next); this.reportStatus() }
    catch {
      this.active = null
      this.activeStarted = false
      const language = this.utteranceLanguages.get(next)
      if (language) this.onPlaybackError(language)
      const id = this.utteranceTiming.get(next)?.chunkId
      if (id !== undefined) this.onSettled(id, false, true)
      this.playNext()
    }
  }
}
