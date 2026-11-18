import type { Language } from './types'
import { languageByCode } from './languageRegistry'
import { voiceForLanguage } from './voices'

export type EnqueueStatus = 'queued' | 'duplicate' | 'queue_full' | 'voice_unavailable' | 'empty'
export type PlaybackStatus = 'idle' | 'playing' | 'paused'

/** Plays completed translations in arrival order without overlapping speech. */
export class SpeechQueue {
  private pending: SpeechSynthesisUtterance[] = []
  private active: SpeechSynthesisUtterance | null = null
  private seen = new Set<number>()
  private utteranceLanguages = new WeakMap<SpeechSynthesisUtterance, Language>()
  private paused = false

  constructor(
    private synth: SpeechSynthesis = window.speechSynthesis,
    private onPlaybackError: (language: Language) => void = () => undefined,
    private onStatusChange: (status: PlaybackStatus, queued: number) => void = () => undefined,
  ) {}

  enqueue(chunkId: number, text: string, language: Language, rate: number): EnqueueStatus {
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
    utterance.onend = () => this.complete(utterance)
    utterance.onerror = () => { this.onPlaybackError(language); this.complete(utterance) }
    this.pending.push(utterance)
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
    if (this.active) { this.active.onend = null; this.active.onerror = null }
    this.active = null
    this.synth.cancel()
    this.reportStatus()
  }

  private complete(utterance: SpeechSynthesisUtterance): void {
    if (this.active !== utterance) return
    this.active = null
    this.playNext()
    this.reportStatus()
  }

  private reportStatus(): void {
    this.onStatusChange(!this.active && !this.pending.length ? 'idle' : this.paused ? 'paused' : this.active ? 'playing' : 'idle', this.pending.length)
  }

  private playNext(): void {
    if (this.paused || this.active || !this.pending.length) return
    const next = this.pending.shift()!
    this.active = next
    try { this.synth.speak(next); this.reportStatus() }
    catch {
      this.active = null
      const language = this.utteranceLanguages.get(next)
      if (language) this.onPlaybackError(language)
      this.playNext()
    }
  }
}
