import { apiBase } from './api'
import type { CaptureTiming, SocketRoundTripTiming } from './latency'
import type { Language, SocketMessage, SourceLanguage } from './types'

export interface SocketConfig {
  source_language: SourceLanguage
  target_language: Language
  save_history: boolean
  session_id?: string
  synthesize_speech?: boolean
  allow_speech_fallback?: boolean
  interim_captions?: boolean
}

interface Callbacks {
  onMessage: (message: SocketMessage, timing?: SocketRoundTripTiming) => void
  onClose: (reason: string) => void
  onDrop: () => void
  onQueueChange?: (depth: number) => void
}

export function socketUrl(base = apiBase): string {
  const url = new URL('/ws/translate', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export class TranslationSocket {
  private socket: WebSocket | null = null
  private inflight = false
  private queued: { wav: ArrayBuffer; capture?: CaptureTiming }[] = []
  private inFlightTiming: { submittedAtMs: number; capture?: CaptureTiming } | null = null
  private config: SocketConfig | null = null
  private intentionalClose = false
  private speechFallbackUsed = false
  private interimEnabled = false
  private interimInFlight: { phraseId: string; revision: number } | null = null

  constructor(private callbacks: Callbacks) {}

  isOpen(): boolean { return this.socket?.readyState === WebSocket.OPEN }
  queueDepth(): number { return this.queued.length + Number(this.inflight) }
  usedSpeechFallback(): boolean { return this.speechFallbackUsed }
  interimAvailable(): boolean { return this.interimEnabled }
  private reportQueue(): void { this.callbacks.onQueueChange?.(this.queueDepth()) }

  async connect(config: SocketConfig): Promise<void> {
    this.close()
    this.speechFallbackUsed = false
    this.interimEnabled = false
    this.config = config
    this.intentionalClose = false
    const socket = new WebSocket(socketUrl())
    this.socket = socket
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => { socket.close(); reject(new Error('Connection timed out. Try again.')) }, 10_000)
      let settled = false
      const fail = (message: string) => {
        if (settled) return
        settled = true
        window.clearTimeout(timeout)
        reject(new Error(message))
      }
      const sendStart = (speech: boolean) => {
        socket.send(JSON.stringify({
          type: 'start', target_language: config.target_language,
          ...(config.source_language === 'auto' ? {} : { source_language: config.source_language }),
          audio_format: 'wav', save_history: config.save_history,
          ...(speech ? { synthesize_speech: true } : {}),
          ...(config.interim_captions ? { interim_captions: true } : {}),
          ...(config.save_history ? { session_id: config.session_id } : {}),
        }))
      }
      socket.onopen = () => sendStart(Boolean(config.synthesize_speech))
      socket.onmessage = (event) => {
        if (this.socket !== socket) return
        const receivedAtMs = performance.now()
        let message: SocketMessage
        try {
          message = JSON.parse(event.data) as SocketMessage
          if (!message || typeof message !== 'object' || typeof message.type !== 'string') throw new Error('Invalid message')
        }
        catch { fail('The server sent an invalid message.'); socket.close(); return }
        if (message.type === 'error' && message.code === 'speech_unavailable' && !settled && config.synthesize_speech && config.allow_speech_fallback) {
          this.speechFallbackUsed = true
          config = { ...config, synthesize_speech: false }
          this.config = config
          this.callbacks.onMessage(message)
          sendStart(false)
          return
        }
        if (message.type === 'ready') {
          this.interimEnabled = Boolean(config.interim_captions && message.interim_captions)
          if (!settled) { settled = true; window.clearTimeout(timeout); resolve() }
        }
        if (message.type === 'interim_caption' || message.type === 'interim_error') {
          if (this.interimInFlight?.phraseId === message.phrase_id && this.interimInFlight.revision === message.revision) this.interimInFlight = null
          if (message.type === 'interim_error' && ['interim_limit', 'interim_rate_limit', 'interim_unavailable'].includes(message.code)) this.interimEnabled = false
          this.callbacks.onMessage(message)
          return
        }
        let timing: SocketRoundTripTiming | undefined
        if ((message.type === 'result' || (message.type === 'error' && Boolean(message.original))) && this.inFlightTiming) {
          timing = { ...this.inFlightTiming, receivedAtMs }
        }
        if ((message.type === 'result' && !this.config?.synthesize_speech) || message.type === 'error' || message.type === 'speech_audio' || message.type === 'speech_error') {
          if (message.type === 'error' && !settled) {
            fail(message.code === 'speech_unavailable' ? 'Azure speech is not configured on the backend. Choose Browser voice and try again.' : message.message)
            socket.close()
          }
          this.inflight = false
          this.inFlightTiming = null
          this.reportQueue()
          this.flush()
        }
        this.callbacks.onMessage(message, timing)
        if (message.type === 'error' && !message.recoverable) socket.close()
      }
      socket.onerror = () => fail('Unable to connect to translation. Check that the backend is running.')
      socket.onclose = (event) => {
        fail(event.code === 1008 ? 'Your session expired or is no longer authorized. Sign in again.' : 'Translation connection closed before it was ready.')
        const isCurrent = this.socket === socket
        if (!isCurrent) return
        this.inflight = false
        this.inFlightTiming = null
        this.interimInFlight = null
        // Queued phrases were never submitted and must not be replayed after reconnect.
        for (const _item of this.queued) this.callbacks.onDrop()
        this.queued = []
        this.reportQueue()
        this.socket = null
        if (!this.intentionalClose) this.callbacks.onClose(event.code === 1008 ? 'Your session expired. Sign in again.' : event.code === 1013 ? 'Translation service is busy. Try again shortly.' : 'Connection lost. Reconnect to continue.')
      }
    })
  }

  sendAudio(wav: ArrayBuffer, capture?: CaptureTiming): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || !this.config) return false
    if (capture?.phraseId === this.interimInFlight?.phraseId) this.interimInFlight = null
    if (this.inflight) {
      if (this.queued.length >= 3) { this.callbacks.onDrop(); return false }
      this.queued.push({ wav, capture })
      this.reportQueue()
      return true
    }
    if (this.socket.bufferedAmount > 2_000_000) { this.callbacks.onDrop(); return false }
    this.inflight = true
    this.reportQueue()
    try {
      if (this.config.save_history) this.socket.send(JSON.stringify({ type: 'chunk', request_id: crypto.randomUUID() }))
      this.inFlightTiming = { submittedAtMs: performance.now(), capture }
      this.socket.send(wav)
      return true
    } catch {
      this.inflight = false
      this.inFlightTiming = null
      this.callbacks.onDrop()
      this.reportQueue()
      this.socket.close()
      return false
    }
  }

  /** Best-effort preview. Never queued or replayed; a final phrase has priority. */
  sendInterim(wav: ArrayBuffer, phraseId: string, revision: number): boolean {
    if (!this.interimEnabled || !this.socket || this.socket.readyState !== WebSocket.OPEN ||
        this.inflight || this.queued.length > 0 || this.interimInFlight ||
        wav.byteLength > 256_000 || this.socket.bufferedAmount > 512_000) return false
    try {
      this.interimInFlight = { phraseId, revision }
      this.socket.send(JSON.stringify({ type: 'interim_audio', phrase_id: phraseId, revision, audio_format: 'wav' }))
      this.socket.send(wav)
      return true
    } catch {
      this.interimInFlight = null
      this.socket.close()
      return false
    }
  }

  cancelInterim(): void {
    const pending = this.interimInFlight
    this.interimInFlight = null
    if (pending && this.socket?.readyState === WebSocket.OPEN) {
      try { this.socket.send(JSON.stringify({ type: 'interim_cancel', phrase_id: pending.phraseId })) }
      catch { this.socket.close() }
    }
  }

  private flush(): void {
    if (this.queued.length) {
      const next = this.queued.shift()!
      this.sendAudio(next.wav, next.capture)
    }
  }

  async stop(): Promise<void> {
    // Stop cancels locally immediately. A phrase already sent may still finish
    // on the server, but it is never replayed after reconnect.
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'stop' }))
    this.close()
  }

  close(): void {
    this.intentionalClose = true
    this.interimEnabled = false
    this.socket?.close()
    this.socket = null
    this.queued = []
    this.inflight = false
    this.inFlightTiming = null
    this.interimInFlight = null
    this.reportQueue()
  }
}
