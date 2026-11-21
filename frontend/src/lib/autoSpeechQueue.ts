import type { Language } from './types'
import { SpeechQueue, type PlaybackStatus, type PlaybackTimingEvent } from './speechQueue'
import { GeneratedSpeechQueue } from './generatedSpeechQueue'

type Phrase = { id: number; text: string; language: Language; rate: number; audio?: string; azureFailed?: boolean; dispatched?: boolean }
export type SpeechProvider = 'azure' | 'browser' | 'captions'

/** Serializes Azure and browser playback. Only one phrase may speak at a time. */
export class AutoSpeechQueue {
  private pending: Phrase[] = []
  private active: Phrase | null = null
  private azureAvailable = true
  private paused = false
  private stopped = false
  private readonly browser: SpeechQueue | null
  private readonly generated: GeneratedSpeechQueue

  constructor(
    synth: SpeechSynthesis | null,
    private onProvider: (provider: SpeechProvider, message?: string) => void,
    private onStatus: (status: PlaybackStatus, queued: number) => void,
    private onTiming: (event: PlaybackTimingEvent | { type: 'azure_started'; chunkId: number; startedAtMs: number; queueWaitMs: number; playbackStartDelayMs: number }) => void,
    private onFailure: () => void = () => undefined,
  ) {
    this.browser = synth?.getVoices ? new SpeechQueue(synth, () => undefined, (state) => this.onStatus(state, this.pending.length),
      (event) => { if (event.type === 'started') this.onProvider('browser'); onTiming(event) },
      (id, started, failed) => { if (this.active?.id !== id) return; if (failed) { this.onFailure(); this.onProvider('captions', started ? 'Browser speech stopped unexpectedly. Captions remain available.' : 'Browser speech could not start. Captions remain available.') } this.finish() }) : null
    this.generated = new GeneratedSpeechQueue((state) => this.onStatus(state, this.pending.length), () => this.onFailure(),
      (id, startedAtMs, queueWaitMs, playbackStartDelayMs) => { this.onProvider('azure'); this.onTiming({ type: 'azure_started', chunkId: id, startedAtMs, queueWaitMs, playbackStartDelayMs }) },
      (id, started, failed) => {
        if (this.active?.id !== id) return
        if (failed && !started) { this.active.azureFailed = true; this.tryBrowser(this.active) }
        else this.finish()
      })
  }

  addResult(id: number, text: string, language: Language, rate: number): boolean {
    if (this.stopped || this.pending.length >= 8 || this.active?.id === id || this.pending.some((item) => item.id === id)) return false
    this.pending.push({ id, text, language, rate })
    this.next()
    return true
  }
  addAudio(id: number, audio: string): void {
    const item = this.active?.id === id ? this.active : this.pending.find((entry) => entry.id === id)
    if (!item || this.stopped || !this.azureAvailable || item.azureFailed || item.dispatched) return
    item.audio = audio
    if (this.active === item) this.playAzure(item)
  }
  speechError(id: number): void {
    const item = this.active?.id === id ? this.active : this.pending.find((entry) => entry.id === id)
    if (!item || this.stopped || item.dispatched) return
    item.azureFailed = true
    if (this.active === item) this.tryBrowser(item)
  }
  disableAzure(): void {
    this.azureAvailable = false
    this.onProvider('captions', 'Azure speech is unavailable. A compatible browser voice will be tried for each phrase.')
    if (this.active) this.tryBrowser(this.active)
  }
  pause(): void { this.paused = true; this.browser?.pause(); this.generated.pause(); this.onStatus('paused', this.pending.length) }
  resume(): void { this.paused = false; this.browser?.resume(); this.generated.resume(); this.next(); if (this.active && !this.active.dispatched) this.dispatch(this.active) }
  stop(): void { this.stopped = true; this.pending = []; this.active = null; this.browser?.stop(); this.generated.stop(); this.onStatus('idle', 0) }
  mute(): void { this.pending = []; this.active = null; this.browser?.stop(); this.generated.stop(); this.onStatus('idle', 0) }

  private next(): void {
    if (this.active || this.paused || this.stopped) return
    this.active = this.pending.shift() || null
    if (this.active) this.dispatch(this.active)
    this.onStatus('idle', this.pending.length)
  }
  private dispatch(item: Phrase): void {
    if (this.paused || this.stopped || this.active !== item || item.dispatched) return
    if (!this.azureAvailable || item.azureFailed) this.tryBrowser(item)
    else if (item.audio) this.playAzure(item)
  }
  private playAzure(item: Phrase): void {
    if (!item.audio || this.paused || this.stopped || this.active !== item) return
    const encoded = item.audio
    item.audio = undefined
    try {
      item.dispatched = true
      if (!this.generated.enqueue(item.id, encoded)) { item.dispatched = false; this.onFailure(); this.tryBrowser(item) }
    } catch { item.dispatched = false; this.onFailure(); this.tryBrowser(item) }
  }
  private tryBrowser(item: Phrase): void {
    if (this.paused || this.stopped || this.active !== item) return
    if (item.dispatched) item.dispatched = false
    const status = this.browser?.enqueue(item.id, item.text, item.language, item.rate)
    if (status === 'queued') item.dispatched = true
    if (status === 'queued') return
    this.onFailure()
    this.onProvider('captions', status === 'voice_unavailable' || !this.browser
      ? 'No matching browser voice is installed. Captions remain available.'
      : 'Translated speech could not be queued. Captions remain available.')
    this.finish()
  }
  private finish(): void { this.active = null; this.next() }
}
