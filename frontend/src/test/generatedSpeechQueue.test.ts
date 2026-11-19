import { afterEach, expect, it, vi } from 'vitest'
import { encodePcmWav } from '../lib/audio'
import { decodeSpeechWav, GeneratedSpeechQueue } from '../lib/generatedSpeechQueue'

afterEach(() => vi.unstubAllGlobals())

function speech(): string {
  const bytes = new Uint8Array(encodePcmWav(new Float32Array(2400).fill(0.1), 24_000, 24_000))
  return btoa(String.fromCharCode(...bytes))
}

it('validates complete provider PCM WAV and rejects malformed audio', () => {
  expect(decodeSpeechWav(speech()).type).toBe('audio/wav')
  expect(() => decodeSpeechWav('not base64!')).toThrow()
  expect(() => decodeSpeechWav(btoa('RIFFbad'))).toThrow()
  expect(() => decodeSpeechWav('A'.repeat(3_000_000))).toThrow('too large')
})

it('plays generated phrases in order without overlap and releases URLs on stop', async () => {
  const players: FakeAudio[] = []
  class FakeAudio {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    onplaying: (() => void) | null = null
    play = vi.fn().mockResolvedValue(undefined)
    pause = vi.fn()
    removeAttribute = vi.fn()
    load = vi.fn()
    constructor(public src: string) { players.push(this) }
  }
  const createObjectURL = vi.fn().mockReturnValueOnce('blob:one').mockReturnValueOnce('blob:two')
  const revokeObjectURL = vi.fn()
  vi.stubGlobal('Audio', FakeAudio)
  vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  const onStarted = vi.fn()
  const queue = new GeneratedSpeechQueue(vi.fn(), vi.fn(), onStarted)
  expect(queue.enqueue(1, speech())).toBe(true)
  expect(queue.enqueue(2, speech())).toBe(true)
  expect(queue.enqueue(1, speech())).toBe(true)
  expect(players).toHaveLength(1)
  players[0].onplaying?.()
  expect(onStarted).toHaveBeenCalledWith(1, expect.any(Number), expect.any(Number), expect.any(Number))
  players[0].onended?.()
  expect(players).toHaveLength(2)
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:one')
  queue.stop()
  expect(players[1].pause).toHaveBeenCalled()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:two')
  expect(createObjectURL).toHaveBeenCalledTimes(2)
})

it('reports autoplay denial, clears the rejected audio, and ignores stale playback events', async () => {
  class BlockedAudio {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    onplaying: (() => void) | null = null
    play = vi.fn().mockRejectedValue(new DOMException('blocked', 'NotAllowedError'))
    pause = vi.fn()
    removeAttribute = vi.fn()
    load = vi.fn()
    constructor(_url: string) {}
  }
  const revoke = vi.fn()
  vi.stubGlobal('Audio', BlockedAudio)
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:blocked'), revokeObjectURL: revoke })
  const onError = vi.fn()
  const started = vi.fn()
  const queue = new GeneratedSpeechQueue(vi.fn(), onError, started)
  queue.enqueue(1, speech())
  await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining('Browser blocked')))
  expect(revoke).toHaveBeenCalledWith('blob:blocked')
  expect(started).not.toHaveBeenCalled()
  queue.stop()
})
