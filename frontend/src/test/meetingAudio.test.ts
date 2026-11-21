import { afterEach, describe, expect, it, vi } from 'vitest'
import { PhraseSegmenter, startMeetingCapture, startMicrophoneCapture } from '../lib/meetingAudio'
import { encodePcmWav } from '../lib/audio'

afterEach(() => vi.unstubAllGlobals())

function feed(segmenter: PhraseSegmenter, value: number, count: number) {
  for (let index = 0; index < count; index++) segmenter.push(new Float32Array(100).fill(value))
}

describe('meeting phrase segmentation', () => {
  it('makes bounded complete-WAV interim snapshots for one active phrase and keeps the final phrase ID', () => {
    const previews: { id: string; revision: number; wav: ArrayBuffer }[] = []
    const finals: string[] = []
    const segmenter = new PhraseSegmenter(1000, (_samples, timing) => finals.push(timing.phraseId!), vi.fn(), {}, (samples, id, revision) => {
      previews.push({ id, revision, wav: encodePcmWav(samples, 1000) })
      return true
    })
    feed(segmenter, 0.2, 80)
    expect(previews.map((item) => item.revision)).toEqual([1, 2, 3, 4])
    expect(new Set(previews.map((item) => item.id)).size).toBe(1)
    for (const preview of previews) {
      const view = new DataView(preview.wav)
      expect(view.getUint32(0, true)).toBe(0x46464952) // RIFF
      expect(view.getUint32(24, true)).toBe(16_000)
      expect(view.getUint16(22, true)).toBe(1)
      expect(preview.wav.byteLength).toBeLessThanOrEqual(256_000)
    }
    feed(segmenter, 0, 7)
    expect(finals).toEqual([previews[0].id])
    segmenter.reset()
    feed(segmenter, 0, 30)
    expect(previews).toHaveLength(4)
  })
  it('waits for speech and a phrase-ending pause before sending complete audio', () => {
    const phrases: Float32Array[] = []
    const segmenter = new PhraseSegmenter(1000, (samples) => phrases.push(samples))
    feed(segmenter, 0, 12)
    feed(segmenter, 0.2, 3)
    expect(phrases).toHaveLength(0)
    feed(segmenter, 0.2, 6)
    feed(segmenter, 0, 7)
    expect(phrases).toHaveLength(1)
    expect(phrases[0].length).toBeGreaterThanOrEqual(900)
    feed(segmenter, 0.2, 9)
    feed(segmenter, 0, 7)
    expect(phrases).toHaveLength(2)
  })

  it('discards noise, short words and unfinished speech on reset', () => {
    const onPhrase = vi.fn()
    const segmenter = new PhraseSegmenter(1000, onPhrase)
    feed(segmenter, 0.001, 20)
    feed(segmenter, 0.2, 3)
    feed(segmenter, 0, 7)
    feed(segmenter, 0.2, 10)
    segmenter.reset()
    feed(segmenter, 0, 10)
    expect(onPhrase).not.toHaveBeenCalled()
  })

  it('distinguishes a dropped active phrase from a gap during silence', () => {
    const segmenter = new PhraseSegmenter(1000, vi.fn())
    feed(segmenter, 0, 5)
    expect(segmenter.hasActivePhrase()).toBe(false)
    feed(segmenter, 0.2, 2)
    expect(segmenter.hasActivePhrase()).toBe(true)
    segmenter.reset()
    expect(segmenter.hasActivePhrase()).toBe(false)
  })

  it('anchors speech end to capture time when buffered blocks arrive late', () => {
    const phrases: number[] = []
    const segmenter = new PhraseSegmenter(1000, (_samples, timing) => phrases.push(timing.speechEndAtMs))
    let capturedAtMs = 0
    for (let index = 0; index < 8; index++) segmenter.push(new Float32Array(100).fill(0.2), capturedAtMs += 100)
    for (let index = 0; index < 7; index++) segmenter.push(new Float32Array(100), capturedAtMs += 100)
    expect(phrases).toHaveLength(1)
    expect(phrases[0]).toBe(800)
  })

  it('bounds uninterrupted speech rather than sending an incomplete phrase', () => {
    const onPhrase = vi.fn()
    const onDrop = vi.fn()
    const segmenter = new PhraseSegmenter(1000, onPhrase, onDrop)
    feed(segmenter, 0.2, 122)
    expect(onPhrase).not.toHaveBeenCalled()
    expect(onDrop).toHaveBeenCalledOnce()
  })
})

describe('browser microphone capture', () => {
  it('does not request permission until capture starts and reports denial', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    expect(getUserMedia).not.toHaveBeenCalled()
    await expect(startMicrophoneCapture(vi.fn(), vi.fn(), vi.fn(), 'selected-device')).rejects.toThrow('Microphone access was denied')
    expect(getUserMedia).toHaveBeenCalledWith({ audio: expect.objectContaining({ deviceId: { exact: 'selected-device' } }), video: false })
  })

  it('uses the same phrase encoder, pauses cleanly, and releases a disconnected microphone', async () => {
    const stop = vi.fn()
    const track = { stop, onended: null as (() => void) | null, getSettings: () => ({}) }
    const getUserMedia = vi.fn().mockResolvedValue({ getAudioTracks: () => [track], getVideoTracks: () => [], getTracks: () => [track] })
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    const close = vi.fn().mockResolvedValue(undefined)
    class FakeContext {
      sampleRate = 1000
      state = 'running'
      destination = {}
      audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
      createMediaStreamSource = () => ({ connect: vi.fn(), disconnect: vi.fn() })
      resume = vi.fn().mockResolvedValue(undefined)
      close = close
    }
    class FakeNode {
      static latest: FakeNode
      port: { onmessage: ((event: MessageEvent<Float32Array>) => void) | null } = { onmessage: null }
      connect = vi.fn()
      disconnect = vi.fn()
      constructor() { FakeNode.latest = this }
    }
    vi.stubGlobal('AudioContext', FakeContext)
    vi.stubGlobal('AudioWorkletNode', FakeNode)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:mic'), revokeObjectURL: vi.fn() })
    const chunks: ArrayBuffer[] = []
    const ended = vi.fn()
    const capture = await startMicrophoneCapture((wav) => chunks.push(wav), ended, vi.fn(), 'selected-device')
    const feed = (value: number, count: number) => {
      for (let index = 0; index < count; index++) FakeNode.latest.port.onmessage?.({ data: new Float32Array(100).fill(value) } as MessageEvent<Float32Array>)
    }
    capture.resume()
    feed(0.2, 9); feed(0, 7)
    expect(chunks).toHaveLength(1)
    expect(new DataView(chunks[0]).getUint32(24, true)).toBe(16_000)
    capture.pause()
    feed(0.2, 9); feed(0, 7)
    expect(chunks).toHaveLength(1)
    track.onended?.()
    await vi.waitFor(() => expect(close).toHaveBeenCalledOnce())
    expect(ended).toHaveBeenCalledOnce()
    expect(stop).toHaveBeenCalledOnce()
  })
})

describe('meeting tab capture', () => {
  it('reports permission denial', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getDisplayMedia: vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError')),
    } })
    await expect(startMeetingCapture(vi.fn(), vi.fn(), vi.fn(), false)).rejects.toThrow('Tab sharing was denied')
  })

  it('rejects sharing without tab audio and stops every acquired track', async () => {
    const stop = vi.fn()
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getDisplayMedia: vi.fn().mockResolvedValue({ getAudioTracks: () => [], getTracks: () => [{ stop, onended: null }] }),
    } })
    await expect(startMeetingCapture(vi.fn(), vi.fn(), vi.fn(), false)).rejects.toThrow('No tab audio was shared')
    expect(stop).toHaveBeenCalledOnce()
  })

  it('encodes pause-bounded tab speech and cleans up on stop', async () => {
    const stopAudio = vi.fn()
    const stopVideo = vi.fn()
    const audioTrack = { stop: stopAudio, onended: null, applyConstraints: vi.fn(), getSettings: () => ({}) }
    const videoTrack = { stop: stopVideo, onended: null, getSettings: () => ({ displaySurface: 'browser' }) }
    const stream = { getAudioTracks: () => [audioTrack], getVideoTracks: () => [videoTrack], getTracks: () => [audioTrack, videoTrack] }
    const getDisplayMedia = vi.fn().mockResolvedValue(stream)
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getDisplayMedia, getSupportedConstraints: () => ({}) } })
    const close = vi.fn().mockResolvedValue(undefined)
    const disconnect = vi.fn()
    class FakeContext {
      sampleRate = 1000
      state = 'running'
      destination = {}
      audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
      createMediaStreamSource = () => ({ connect: vi.fn(), disconnect })
      resume = vi.fn().mockResolvedValue(undefined)
      close = close
    }
    class FakeNode {
      static latest: FakeNode
      port: { onmessage: ((event: MessageEvent<Float32Array>) => void) | null } = { onmessage: null }
      connect = vi.fn()
      disconnect = disconnect
      constructor() { FakeNode.latest = this }
    }
    vi.stubGlobal('AudioContext', FakeContext)
    vi.stubGlobal('AudioWorkletNode', FakeNode)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:meeting'), revokeObjectURL: vi.fn() })
    const chunks: ArrayBuffer[] = []
    const phraseTimings: { captureDurationMs: number; speechEndAtMs: number }[] = []
    const onActivity = vi.fn()
    const capture = await startMeetingCapture((wav, timing) => { chunks.push(wav); phraseTimings.push(timing) }, vi.fn(), vi.fn(), false, onActivity)
    expect(getDisplayMedia).toHaveBeenCalledWith(expect.objectContaining({ video: expect.any(Object), audio: expect.any(Object) }))
    const push = (value: number, count: number) => {
      for (let index = 0; index < count; index++) FakeNode.latest.port.onmessage?.({ data: new Float32Array(100).fill(value) } as MessageEvent<Float32Array>)
    }
    capture.resume()
    push(0.2, 9)
    push(0, 7)
    expect(onActivity).toHaveBeenCalledWith(expect.any(Number))
    expect(onActivity.mock.calls.some(([level]) => level > 0)).toBe(true)
    expect(chunks).toHaveLength(1)
    expect(new DataView(chunks[0]).getUint32(24, true)).toBe(16_000)
    expect(phraseTimings[0].captureDurationMs).toBeGreaterThan(0)
    expect(Number.isFinite(phraseTimings[0].speechEndAtMs)).toBe(true)
    capture.pause()
    expect(onActivity).toHaveBeenLastCalledWith(0)
    push(0.2, 9)
    push(0, 7)
    expect(chunks).toHaveLength(1)
    await capture.stop()
    expect(stopAudio).toHaveBeenCalledOnce()
    expect(stopVideo).toHaveBeenCalledOnce()
    expect(close).toHaveBeenCalledOnce()
  })
})
