import { afterEach, describe, expect, it, vi } from 'vitest'
import { PhraseSegmenter, startMeetingCapture } from '../lib/meetingAudio'

afterEach(() => vi.unstubAllGlobals())

function feed(segmenter: PhraseSegmenter, value: number, count: number) {
  for (let index = 0; index < count; index++) segmenter.push(new Float32Array(100).fill(value))
}

describe('meeting phrase segmentation', () => {
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

  it('bounds uninterrupted speech rather than sending an incomplete phrase', () => {
    const onPhrase = vi.fn()
    const onDrop = vi.fn()
    const segmenter = new PhraseSegmenter(1000, onPhrase, onDrop)
    feed(segmenter, 0.2, 122)
    expect(onPhrase).not.toHaveBeenCalled()
    expect(onDrop).toHaveBeenCalledOnce()
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
