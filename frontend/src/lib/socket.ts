import { apiBase } from './api'
import type { CaptureTiming, SocketRoundTripTiming } from './latency'
import type { Language, SocketMessage, SourceLanguage } from './types'

export interface SocketConfig {
  source_language: SourceLanguage
  target_language: Language
  save_history: boolean
  session_id?: string
}

interface Callbacks {
  onMessage: (message: SocketMessage, timing?: SocketRoundTripTiming) => void
  onClose: (reason: string) => void
  onDrop: () => void
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
  private drainWaiters: (() => void)[] = []
  private intentionalClose = false

  constructor(private callbacks: Callbacks) {}

  isOpen(): boolean { return this.socket?.readyState === WebSocket.OPEN }

  async connect(config: SocketConfig): Promise<void> {
    this.close()
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
      socket.onopen = () => {
        socket.send(JSON.stringify({
          type: 'start', target_language: config.target_language,
          ...(config.source_language === 'auto' ? {} : { source_language: config.source_language }),
          audio_format: 'wav', save_history: config.save_history,
          ...(config.save_history ? { session_id: config.session_id } : {}),
        }))
      }
      socket.onmessage = (event) => {
        const receivedAtMs = performance.now()
        let message: SocketMessage
        try { message = JSON.parse(event.data) as SocketMessage }
        catch { fail('The server sent an invalid message.'); socket.close(); return }
        if (message.type === 'ready') {
          if (!settled) { settled = true; window.clearTimeout(timeout); resolve() }
        }
        let timing: SocketRoundTripTiming | undefined
        if (message.type === 'result' && this.inFlightTiming) {
          timing = { ...this.inFlightTiming, receivedAtMs }
        }
        if (message.type === 'result' || message.type === 'error') {
          if (message.type === 'error' && !settled) { fail(message.message); socket.close() }
          this.inflight = false
          this.inFlightTiming = null
          this.flush()
        }
        this.callbacks.onMessage(message, timing)
        if (message.type === 'error' && !message.recoverable) socket.close()
      }
      socket.onerror = () => fail('Unable to connect to translation. Check that the backend is running.')
      socket.onclose = (event) => {
        fail(event.code === 1008 ? 'Your session expired or is no longer authorized. Sign in again.' : 'Translation connection closed before it was ready.')
        this.inflight = false
        this.inFlightTiming = null
        this.queued = []
        this.resolveDrain()
        const isCurrent = this.socket === socket
        if (isCurrent) this.socket = null
        if (isCurrent && !this.intentionalClose) this.callbacks.onClose(event.code === 1008 ? 'Your session expired. Sign in again.' : 'Connection lost. Reconnect to continue.')
      }
    })
  }

  sendAudio(wav: ArrayBuffer, capture?: CaptureTiming): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || !this.config) return false
    if (this.inflight) {
      if (this.queued.length >= 3) { this.callbacks.onDrop(); return false }
      this.queued.push({ wav, capture })
      return true
    }
    this.inflight = true
    if (this.config.save_history) this.socket.send(JSON.stringify({ type: 'chunk', request_id: crypto.randomUUID() }))
    this.inFlightTiming = { submittedAtMs: performance.now(), capture }
    this.socket.send(wav)
    return true
  }

  private flush(): void {
    if (this.queued.length) {
      const next = this.queued.shift()!
      this.sendAudio(next.wav, next.capture)
    } else this.resolveDrain()
  }

  private resolveDrain(): void {
    if (this.inflight || this.queued.length) return
    this.drainWaiters.splice(0).forEach((resolve) => resolve())
  }

  async stop(): Promise<void> {
    if (this.inflight || this.queued.length) {
      let timeout: number | undefined
      await Promise.race([
        new Promise<void>((resolve) => this.drainWaiters.push(resolve)),
        new Promise<void>((resolve) => { timeout = window.setTimeout(resolve, 130_000) }),
      ])
      if (timeout !== undefined) window.clearTimeout(timeout)
    }
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'stop' }))
    this.intentionalClose = true
    this.socket?.close()
    this.socket = null
  }

  close(): void {
    this.intentionalClose = true
    this.socket?.close()
    this.socket = null
    this.queued = []
    this.inflight = false
    this.inFlightTiming = null
    this.resolveDrain()
  }
}
