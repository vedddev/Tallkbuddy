const TARGET_RATE = 16_000
const CHUNK_SECONDS = 1.25

export function encodePcmWav(input: Float32Array, inputRate: number, outputRate = TARGET_RATE): ArrayBuffer {
  if (!Number.isFinite(inputRate) || inputRate <= 0 || !Number.isFinite(outputRate) || outputRate <= 0) {
    throw new Error('Invalid audio sample rate')
  }
  const count = Math.max(1, Math.floor(input.length * outputRate / inputRate))
  const bytes = new ArrayBuffer(44 + count * 2)
  const view = new DataView(bytes)
  const write = (at: number, value: string) => [...value].forEach((letter, index) => view.setUint8(at + index, letter.charCodeAt(0)))
  write(0, 'RIFF')
  view.setUint32(4, bytes.byteLength - 8, true)
  write(8, 'WAVE')
  write(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, outputRate, true)
  view.setUint32(28, outputRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, count * 2, true)
  for (let index = 0; index < count; index++) {
    const position = index * inputRate / outputRate
    const left = Math.min(Math.floor(position), input.length - 1)
    const right = Math.min(left + 1, input.length - 1)
    const sample = input[left] + (input[right] - input[left]) * (position - left)
    const clamped = Math.max(-1, Math.min(1, Number.isFinite(sample) ? sample : 0))
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 32768 : clamped * 32767, true)
  }
  return bytes
}

export const captureWorkletCode = `
class TalkBuddyCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels && channels.length && channels[0].length) {
      const mono = new Float32Array(channels[0].length);
      for (const channel of channels) {
        for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
      }
      this.port.postMessage(mono);
    }
    return true;
  }
}
registerProcessor('talkbuddy-capture', TalkBuddyCapture);
`

export interface AudioCapture { stop: () => Promise<void>; abort: () => Promise<void> }

export async function startAudioCapture(onChunk: (wav: ArrayBuffer) => void): Promise<AudioCapture> {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access requires a secure browser context.')
  let stream: MediaStream | null = null
  let context: AudioContext | null = null
  let moduleUrl: string | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let node: AudioWorkletNode | null = null
  let stopped = false
  let samples: Float32Array[] = []
  let sampleCount = 0
  const cleanup = async () => {
    stopped = true
    if (node) { node.port.onmessage = null; node.disconnect() }
    source?.disconnect()
    stream?.getTracks().forEach((track) => track.stop())
    if (context && context.state !== 'closed') await context.close()
    if (moduleUrl) URL.revokeObjectURL(moduleUrl)
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
    context = new AudioContext()
    if (!context.audioWorklet) throw new Error('This browser does not support AudioWorklet recording.')
    moduleUrl = URL.createObjectURL(new Blob([captureWorkletCode], { type: 'text/javascript' }))
    await context.audioWorklet.addModule(moduleUrl)
    source = context.createMediaStreamSource(stream)
    node = new AudioWorkletNode(context, 'talkbuddy-capture')
    const chunkSamples = Math.floor(context.sampleRate * CHUNK_SECONDS)
    const emit = (length: number) => {
      if (length <= 0) return
      const joined = new Float32Array(sampleCount)
      let cursor = 0
      for (const block of samples) { joined.set(block, cursor); cursor += block.length }
      onChunk(encodePcmWav(joined.subarray(0, length), context!.sampleRate))
      const remaining = joined.slice(length)
      samples = remaining.length ? [remaining] : []
      sampleCount = remaining.length
    }
    node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (stopped) return
      const block = event.data
      if (!(block instanceof Float32Array) || !block.length) return
      samples.push(block)
      sampleCount += block.length
      while (sampleCount >= chunkSamples) emit(chunkSamples)
    }
    source.connect(node)
    node.connect(context.destination)
    await context.resume()
    return {
      stop: async () => {
        if (stopped) return
        if (sampleCount >= context!.sampleRate * 0.25) emit(sampleCount)
        await cleanup()
      },
      abort: async () => { if (!stopped) await cleanup() },
    }
  } catch (error) {
    await cleanup()
    if (error instanceof DOMException && error.name === 'NotAllowedError') {
      throw new Error('Microphone permission was denied. Allow access in your browser settings and retry.')
    }
    throw error
  }
}
