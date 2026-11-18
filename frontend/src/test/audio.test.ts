import { afterEach, describe, expect, it, vi } from 'vitest'
import { encodePcmWav, startAudioCapture } from '../lib/audio'

afterEach(() => { vi.unstubAllGlobals() })

describe('PCM WAV encoding', () => {
  it('creates an independently decodable mono 16-bit WAV file', () => {
    const wav = encodePcmWav(new Float32Array([0, 1, -1, 0.5]), 16_000)
    const bytes = new Uint8Array(wav)
    const view = new DataView(wav)
    expect(String.fromCharCode(...bytes.slice(0, 4))).toBe('RIFF')
    expect(String.fromCharCode(...bytes.slice(8, 12))).toBe('WAVE')
    expect(view.getUint32(4, true)).toBe(wav.byteLength - 8)
    expect(view.getUint16(20, true)).toBe(1)
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(24, true)).toBe(16_000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(view.getUint32(40, true)).toBe(8)
    expect(view.getInt16(46, true)).toBe(32767)
    expect(view.getInt16(48, true)).toBe(-32768)
  })

  it('downsamples and rejects invalid sample rates', () => {
    expect(new DataView(encodePcmWav(new Float32Array(48_000), 48_000)).getUint32(40, true)).toBe(32_000)
    expect(() => encodePcmWav(new Float32Array(1), 0)).toThrow('Invalid audio sample rate')
  })
})

describe('microphone capture', () => {
  it('reports denied permission without opening an audio context', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    await expect(startAudioCapture(vi.fn())).rejects.toThrow('Microphone permission was denied')
  })

  it('emits complete WAV chunks and stops tracks on cleanup', async () => {
    const trackStop = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: trackStop }] })
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    const close = vi.fn().mockResolvedValue(undefined)
    const disconnect = vi.fn()
    class FakeContext {
      sampleRate = 16_000
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
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:worklet'), revokeObjectURL: vi.fn() })
    const chunks: ArrayBuffer[] = []
    const capture = await startAudioCapture((wav) => chunks.push(wav))
    FakeNode.latest.port.onmessage?.({ data: new Float32Array(20_000) } as MessageEvent<Float32Array>)
    expect(chunks).toHaveLength(1)
    expect(new DataView(chunks[0]).getUint32(24, true)).toBe(16_000)
    await capture.stop()
    expect(trackStop).toHaveBeenCalledOnce()
    expect(close).toHaveBeenCalledOnce()
    expect(disconnect).toHaveBeenCalled()
  })
})
