import { afterEach, describe, expect, it, vi } from 'vitest'
import { TranslationSocket } from '../lib/socket'
import { languageRegistry } from '../lib/languageRegistry'
import type { SocketMessage } from '../lib/types'

class FakeWebSocket {
  static OPEN = 1
  static instance: FakeWebSocket
  readyState = 0
  sent: (string | ArrayBuffer)[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  constructor(public url: string) { FakeWebSocket.instance = this }
  send(payload: string | ArrayBuffer) { this.sent.push(payload) }
  close() { this.readyState = 3; this.onclose?.({ code: 1000 }) }
  open() { this.readyState = 1; this.onopen?.() }
  receive(message: object) { this.onmessage?.({ data: JSON.stringify(message) }) }
}

afterEach(() => vi.unstubAllGlobals())

describe('translation socket protocol', () => {
  it.each(languageRegistry)('serializes $code as the selected WebSocket target', async (entry) => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const socket = new TranslationSocket({ onMessage: vi.fn(), onClose: vi.fn(), onDrop: vi.fn() })
    const connected = socket.connect({ source_language: 'auto', target_language: entry.code, save_history: false })
    const transport = FakeWebSocket.instance
    transport.open()
    expect(JSON.parse(transport.sent[0] as string).target_language).toBe(entry.code)
    transport.receive({ type: 'ready', target_language: entry.code, source_language: null, audio_format: 'wav' })
    await connected
    socket.close()
  })

  it('starts with cookies in the handshake, sends WAV chunks sequentially, and stops', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const messages: SocketMessage[] = []
    const socket = new TranslationSocket({ onMessage: (message) => messages.push(message), onClose: vi.fn(), onDrop: vi.fn() })
    const connected = socket.connect({ source_language: 'auto', target_language: 'fr', save_history: false })
    const transport = FakeWebSocket.instance
    expect(transport.url).toContain('/ws/translate')
    expect(transport.url).not.toContain('token=')
    transport.open()
    expect(JSON.parse(transport.sent[0] as string)).toEqual({ type: 'start', target_language: 'fr', audio_format: 'wav', save_history: false })
    transport.receive({ type: 'ready', target_language: 'fr', source_language: null, audio_format: 'wav' })
    await connected
    const first = new ArrayBuffer(44)
    const second = new ArrayBuffer(46)
    socket.sendAudio(first)
    socket.sendAudio(second)
    expect(transport.sent).toHaveLength(2)
    transport.receive({ type: 'result', chunk_id: 1, original: 'Hello', translated: 'Bonjour', detected_language: 'en', target_language: 'fr', processing_time_ms: 10 })
    expect(transport.sent[2]).toBe(second)
    transport.receive({ type: 'result', chunk_id: 2, original: 'Next', translated: 'Suivant', detected_language: 'en', target_language: 'fr', processing_time_ms: 10 })
    await socket.stop()
    expect(JSON.parse(transport.sent[3] as string)).toEqual({ type: 'stop' })
    expect(messages.filter((message) => message.type === 'result')).toHaveLength(2)
  })

  it('associates local send/receive timing with the correct queued phrase', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const onMessage = vi.fn()
    const socket = new TranslationSocket({ onMessage, onClose: vi.fn(), onDrop: vi.fn() })
    const connected = socket.connect({ source_language: 'auto', target_language: 'fr', save_history: false })
    const transport = FakeWebSocket.instance
    transport.open()
    transport.receive({ type: 'ready', target_language: 'fr', source_language: null, audio_format: 'wav' })
    await connected
    const clock = vi.spyOn(performance, 'now')
    clock.mockReturnValue(100)
    socket.sendAudio(new ArrayBuffer(44), { speechEndAtMs: 40, captureDurationMs: 1000 })
    socket.sendAudio(new ArrayBuffer(46), { speechEndAtMs: 80, captureDurationMs: 900 })
    clock.mockReturnValue(220)
    transport.receive({ type: 'result', chunk_id: 1, original: 'One', translated: 'Un', target_language: 'fr', detected_language: 'en', processing_time_ms: 100 })
    expect(onMessage).toHaveBeenLastCalledWith(expect.objectContaining({ chunk_id: 1 }), {
      submittedAtMs: 100, receivedAtMs: 220, capture: { speechEndAtMs: 40, captureDurationMs: 1000 },
    })
    clock.mockReturnValue(310)
    transport.receive({ type: 'result', chunk_id: 2, original: 'Two', translated: 'Deux', target_language: 'fr', detected_language: 'en', processing_time_ms: 80 })
    expect(onMessage).toHaveBeenLastCalledWith(expect.objectContaining({ chunk_id: 2 }), {
      submittedAtMs: 220, receivedAtMs: 310, capture: { speechEndAtMs: 80, captureDurationMs: 900 },
    })
    clock.mockRestore()
    socket.close()
  })

  it('requires ready and surfaces a failed handshake', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const socket = new TranslationSocket({ onMessage: vi.fn(), onClose: vi.fn(), onDrop: vi.fn() })
    const connected = socket.connect({ source_language: 'en', target_language: 'fr', save_history: true, session_id: 'session-id' })
    FakeWebSocket.instance.open()
    expect(JSON.parse(FakeWebSocket.instance.sent[0] as string).session_id).toBe('session-id')
    FakeWebSocket.instance.receive({ type: 'error', code: 'history_disabled', message: 'History saving is disabled', recoverable: true })
    await expect(connected).rejects.toThrow('History saving is disabled')
  })

  it('explains an authentication rejection before the socket is ready', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const socket = new TranslationSocket({ onMessage: vi.fn(), onClose: vi.fn(), onDrop: vi.fn() })
    const connected = socket.connect({ source_language: 'auto', target_language: 'hi', save_history: false })
    FakeWebSocket.instance.onclose?.({ code: 1008 })
    await expect(connected).rejects.toThrow('Sign in again')
  })

  it('sends request IDs and keeps a bounded FIFO phrase queue', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const onDrop = vi.fn()
    const onClose = vi.fn()
    const socket = new TranslationSocket({ onMessage: vi.fn(), onClose, onDrop })
    const connected = socket.connect({ source_language: 'en', target_language: 'fr', save_history: true, session_id: 'session-id' })
    const transport = FakeWebSocket.instance
    transport.open()
    transport.receive({ type: 'ready', target_language: 'fr', source_language: 'en', audio_format: 'wav' })
    await connected
    expect(socket.sendAudio(new ArrayBuffer(44))).toBe(true)
    expect(socket.sendAudio(new ArrayBuffer(46))).toBe(true)
    expect(socket.sendAudio(new ArrayBuffer(48))).toBe(true)
    expect(socket.sendAudio(new ArrayBuffer(50))).toBe(true)
    expect(socket.sendAudio(new ArrayBuffer(52))).toBe(false)
    expect(JSON.parse(transport.sent[1] as string)).toMatchObject({ type: 'chunk', request_id: expect.any(String) })
    expect(onDrop).toHaveBeenCalledOnce()
    transport.receive({ type: 'result', chunk_id: 1, original: 'Hello', translated: 'Bonjour', detected_language: 'en', target_language: 'fr', processing_time_ms: 10 })
    expect((transport.sent[4] as ArrayBuffer).byteLength).toBe(46)
    transport.receive({ type: 'result', chunk_id: 2, original: 'Next', translated: 'Suivant', detected_language: 'en', target_language: 'fr', processing_time_ms: 10 })
    expect((transport.sent[6] as ArrayBuffer).byteLength).toBe(48)
    transport.close()
    expect(onClose).toHaveBeenCalledOnce()
  })
})
