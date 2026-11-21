import { expect, it, vi } from 'vitest'
import { captureWorkletCode, encodePcmWav, unpackAudioBlock } from '../lib/audio'
import { DEFAULT_VAD_OPTIONS, PhraseSegmenter } from '../lib/meetingAudio'

it('batches stereo audio in the worklet and bounds delivery until acknowledgement', () => {
  let Processor: new () => { port: { onmessage: ((event: { data: string }) => void) | null; postMessage: ReturnType<typeof vi.fn> }; process: (inputs: Float32Array[][]) => boolean }
  class FakeBase { port = { onmessage: null as ((event: { data: string }) => void) | null, postMessage: vi.fn() } }
  new Function('AudioWorkletProcessor', 'registerProcessor', 'sampleRate', 'currentTime', captureWorkletCode)(
    FakeBase, (_name: string, value: typeof Processor) => { Processor = value }, 48_000, 0,
  )
  const processor = new Processor!()
  const stereo = [new Float32Array(128).fill(0.8), new Float32Array(128).fill(-0.4)]
  for (let i = 0; i < 8; i++) processor.process([stereo])
  expect(processor.port.postMessage).toHaveBeenCalledTimes(1)
  const first = unpackAudioBlock(processor.port.postMessage.mock.calls[0][0])!
  expect(first.samples).toHaveLength(960)
  expect(first.samples[0]).toBeCloseTo(0.2)
  for (let i = 0; i < 8; i++) processor.process([stereo])
  expect(processor.port.postMessage).toHaveBeenCalledTimes(1)
  processor.port.onmessage?.({ data: 'ack' })
  for (let i = 0; i < 8; i++) processor.process([stereo])
  const second = unpackAudioBlock(processor.port.postMessage.mock.calls[1][0])!
  expect(second.droppedSamples).toBe(0)
  for (let i = 0; i < 80; i++) processor.process([stereo])
  processor.port.onmessage?.({ data: 'ack' })
  const afterOverflow = unpackAudioBlock(processor.port.postMessage.mock.calls[2][0])!
  expect(afterOverflow.droppedSamples).toBeGreaterThan(0)
})

it('resamples common browser rates into bounded mono 16 kHz PCM without amplification', () => {
  for (const rate of [16_000, 44_100, 48_000]) {
    const input = new Float32Array(rate / 10).fill(0.25)
    const wav = encodePcmWav(input, rate)
    const view = new DataView(wav)
    expect(view.getUint32(24, true)).toBe(16_000)
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint16(34, true)).toBe(16)
    expect(view.getUint32(40, true)).toBe(3200)
    expect(view.getInt16(44, true)).toBeGreaterThan(0)
    expect(view.getInt16(44, true)).toBeLessThan(9_000)
  }
  expect(() => encodePcmWav(new Float32Array(), 48_000)).toThrow('empty audio')
})

it('uses bounded VAD settings and preserves onset/end timing for a complete phrase', () => {
  const phrases: { start: number | null | undefined; end: number }[] = []
  const segmenter = new PhraseSegmenter(1000, (_samples, timing) => phrases.push({ start: timing.speechStartAtMs, end: timing.speechEndAtMs }), vi.fn(), { endingSilenceMs: 500 })
  for (let i = 0; i < 10; i++) segmenter.push(new Float32Array(100).fill(0.001))
  for (let i = 0; i < 8; i++) segmenter.push(new Float32Array(100).fill(0.2))
  for (let i = 0; i < 5; i++) segmenter.push(new Float32Array(100))
  expect(phrases).toHaveLength(1)
  expect(phrases[0].start).not.toBeNull()
  expect(Number.isFinite(phrases[0].end)).toBe(true)
  expect(DEFAULT_VAD_OPTIONS.endingSilenceMs).toBe(700)
  expect(() => new PhraseSegmenter(1000, vi.fn(), vi.fn(), { maximumPhraseMs: 60_000 })).toThrow('Invalid VAD')
})
