import { captureWorkletCode, encodePcmWav, unpackAudioBlock } from './audio'
import type { CaptureTiming } from './latency'

const OUTPUT_RATE = 16_000
const MAX_WAV_BYTES = 1_000_000

export interface VadOptions {
  onsetMs: number
  minimumSpeechMs: number
  endingSilenceMs: number
  maximumPhraseMs: number
  prerollMs: number
  trailingPaddingMs: number
}

export const DEFAULT_VAD_OPTIONS: Readonly<VadOptions> = Object.freeze({
  onsetMs: 120, minimumSpeechMs: 600, endingSilenceMs: 700,
  maximumPhraseMs: 12_000, prerollMs: 250, trailingPaddingMs: 150,
})

function vadOptions(overrides: Partial<VadOptions>): VadOptions {
  const options = { ...DEFAULT_VAD_OPTIONS, ...overrides }
  if (options.onsetMs < 40 || options.onsetMs > 500 || options.minimumSpeechMs < 250 || options.minimumSpeechMs > 2_000 ||
      options.endingSilenceMs < 300 || options.endingSilenceMs > 2_000 || options.maximumPhraseMs < 2_000 || options.maximumPhraseMs > 20_000 ||
      options.prerollMs < 0 || options.prerollMs > 500 || options.trailingPaddingMs < 0 || options.trailingPaddingMs > 300 ||
      Object.values(options).some((value) => !Number.isFinite(value))) throw new Error('Invalid VAD configuration')
  return options
}

export class PhraseSegmenter {
  private preroll: Float32Array[] = []
  private prerollSamples = 0
  private segment: Float32Array[] = []
  private segmentSamples = 0
  private voicedSamples = 0
  private candidateSamples = 0
  private trailingSilence = 0
  private noiseFloor = 0.002
  private active = false
  private speechStartAtMs: number | null = null
  private options: VadOptions

  constructor(
    private sampleRate: number,
    private onPhrase: (samples: Float32Array, timing: CaptureTiming) => void,
    private onDrop: () => void = () => undefined,
    options: Partial<VadOptions> = {},
  ) { this.options = vadOptions(options) }

  push(block: Float32Array): void {
    if (!block.length) return
    let sum = 0
    for (const sample of block) sum += sample * sample
    const rms = Math.sqrt(sum / block.length)
    const voiced = rms >= Math.max(0.012, this.noiseFloor * 2.8)
    if (!voiced) this.noiseFloor = Math.min(0.02, this.noiseFloor * 0.995 + rms * 0.005)

    if (!this.active) {
      this.preroll.push(block.slice())
      this.prerollSamples += block.length
      const maxPreroll = Math.floor(this.sampleRate * this.options.prerollMs / 1000)
      while (this.prerollSamples > maxPreroll && this.preroll.length > 1) {
        this.prerollSamples -= this.preroll.shift()!.length
      }
      this.candidateSamples = voiced ? this.candidateSamples + block.length : 0
      if (this.candidateSamples < this.sampleRate * this.options.onsetMs / 1000) return
      this.active = true
      this.speechStartAtMs = performance.now() - this.candidateSamples / this.sampleRate * 1000
      this.segment = this.preroll
      this.segmentSamples = this.prerollSamples
      this.voicedSamples = this.candidateSamples
      this.preroll = []
      this.prerollSamples = 0
      this.trailingSilence = 0
      return
    }

    this.segment.push(block.slice())
    this.segmentSamples += block.length
    if (voiced) {
      this.voicedSamples += block.length
      this.trailingSilence = 0
    } else {
      this.trailingSilence += block.length
    }
    if (this.trailingSilence >= this.sampleRate * this.options.endingSilenceMs / 1000) {
      this.finish()
    } else if (this.segmentSamples >= this.sampleRate * this.options.maximumPhraseMs / 1000) {
      // A long uninterrupted utterance has no safe phrase boundary.
      if (this.trailingSilence >= this.sampleRate * 0.18) this.finish()
      else { this.onDrop(); this.reset() }
    }
  }

  reset(): void {
    this.preroll = []
    this.prerollSamples = 0
    this.segment = []
    this.segmentSamples = 0
    this.voicedSamples = 0
    this.candidateSamples = 0
    this.trailingSilence = 0
    this.active = false
    this.speechStartAtMs = null
  }

  private finish(): void {
    if (this.voicedSamples < this.sampleRate * this.options.minimumSpeechMs / 1000) { this.reset(); return }
    // The phrase boundary is detected after trailing silence. Estimate the
    // speech end on this browser's monotonic clock without changing VAD.
    const speechEndAtMs = performance.now() - this.trailingSilence / this.sampleRate * 1000
    const keep = Math.min(this.segmentSamples, this.segmentSamples - this.trailingSilence + Math.floor(this.sampleRate * this.options.trailingPaddingMs / 1000))
    const speechStartAtMs = this.speechStartAtMs
    const joined = new Float32Array(keep)
    let cursor = 0
    for (const block of this.segment) {
      const take = Math.min(block.length, keep - cursor)
      if (take <= 0) break
      joined.set(block.subarray(0, take), cursor)
      cursor += take
    }
    this.reset()
    this.onPhrase(joined, { speechEndAtMs, speechStartAtMs, captureDurationMs: joined.length / this.sampleRate * 1000 })
  }
}

export interface MeetingCapture {
  pause: () => void
  resume: () => void
  stop: () => Promise<void>
  setOriginalMuted: (muted: boolean) => Promise<boolean>
  originalMuteSupported: boolean
}

export async function startMeetingCapture(
  onChunk: (wav: ArrayBuffer, timing: CaptureTiming) => void,
  onEnded: () => void,
  onDrop: () => void,
  muteOriginal: boolean,
  onActivity?: (level: number) => void,
  onDroppedSamples?: (count: number) => void,
): Promise<MeetingCapture> {
  return startPhraseCapture('meeting', onChunk, onEnded, onDrop, muteOriginal, onActivity, undefined, onDroppedSamples)
}

export async function startMicrophoneCapture(
  onChunk: (wav: ArrayBuffer, timing: CaptureTiming) => void,
  onEnded: () => void,
  onDrop: () => void,
  deviceId?: string,
  onActivity?: (level: number) => void,
  onDroppedSamples?: (count: number) => void,
): Promise<MeetingCapture> {
  return startPhraseCapture('microphone', onChunk, onEnded, onDrop, false, onActivity, deviceId, onDroppedSamples)
}

async function startPhraseCapture(
  mode: 'meeting' | 'microphone',
  onChunk: (wav: ArrayBuffer, timing: CaptureTiming) => void,
  onEnded: () => void,
  onDrop: () => void,
  muteOriginal: boolean,
  onActivity?: (level: number) => void,
  deviceId?: string,
  onDroppedSamples?: (count: number) => void,
): Promise<MeetingCapture> {
  if (mode === 'meeting' && !navigator.mediaDevices?.getDisplayMedia) throw new Error('Tab audio capture is unavailable in this browser or context.')
  if (mode === 'microphone' && !navigator.mediaDevices?.getUserMedia) throw new Error('Microphone capture is unavailable in this browser or context.')
  // Permission is requested from the Start/Share click, before network requests.
  let stream: MediaStream
  try {
    stream = mode === 'meeting' ? await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'browser' },
      audio: { suppressLocalAudioPlayback: muteOriginal },
      selfBrowserSurface: 'exclude',
    } as DisplayMediaStreamOptions) : await navigator.mediaDevices.getUserMedia({
      audio: { ...(deviceId ? { deviceId: { exact: deviceId } } : {}), channelCount: 1, echoCancellation: true, noiseSuppression: true },
      video: false,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'NotAllowedError') throw new Error(mode === 'meeting' ? 'Tab sharing was denied. Choose the meeting tab and allow audio sharing.' : 'Microphone access was denied. Allow microphone access in browser site settings and try again.')
    if (mode === 'microphone' && cause instanceof DOMException && cause.name === 'NotFoundError') throw new Error('The selected microphone is unavailable. Choose another input device.')
    if (mode === 'microphone' && cause instanceof DOMException && cause.name === 'NotReadableError') throw new Error('The microphone could not be opened. Check device connections and other applications.')
    throw cause
  }
  let context: AudioContext | null = null
  let moduleUrl: string | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let node: AudioWorkletNode | null = null
  let stopped = false
  let paused = true
  let lastActivityAt = -Infinity
  let captureStartedAtMs: number | null = null
  const cleanup = async () => {
    if (stopped) return
    stopped = true
    onActivity?.(0)
    if (node) { node.port.onmessage = null; node.disconnect() }
    source?.disconnect()
    stream.getTracks().forEach((track) => { track.onended = null; track.stop() })
    if (context && context.state !== 'closed') await context.close()
    if (moduleUrl) URL.revokeObjectURL(moduleUrl)
  }
  try {
    const audioTrack = stream.getAudioTracks()[0]
    if (!audioTrack) throw new Error(mode === 'meeting' ? 'No tab audio was shared. Select a browser tab and enable Share tab audio.' : 'The selected microphone has no audio track.')
    const displaySurface = stream.getVideoTracks()[0]?.getSettings?.().displaySurface
    if (mode === 'meeting' && displaySurface && displaySurface !== 'browser') throw new Error('Select the meeting browser tab, not a screen or window.')
    context = new AudioContext()
    if (!context.audioWorklet) throw new Error('This browser does not support AudioWorklet capture.')
    const segmenter = new PhraseSegmenter(context.sampleRate, (samples, timing) => {
      const encodingStartedAtMs = performance.now()
      const wav = encodePcmWav(samples, context!.sampleRate, OUTPUT_RATE)
      if (wav.byteLength <= MAX_WAV_BYTES) onChunk(wav, {
        ...timing, captureStartedAtMs, encodingMs: Math.max(0, performance.now() - encodingStartedAtMs),
        phraseEncodedAtMs: performance.now(), phraseId: crypto.randomUUID(),
      })
      else onDrop()
    }, onDrop)
    moduleUrl = URL.createObjectURL(new Blob([captureWorkletCode], { type: 'text/javascript' }))
    await context.audioWorklet.addModule(moduleUrl)
    source = context.createMediaStreamSource(stream)
    node = new AudioWorkletNode(context, 'talkbuddy-capture')
    node.port.onmessage = (event: MessageEvent<unknown>) => {
      if (stopped) return
      const block = unpackAudioBlock(event.data)
      node?.port.postMessage?.('ack')
      if (block?.droppedSamples) { segmenter.reset(); onDroppedSamples?.(block.droppedSamples) }
      if (!paused && block?.samples.length) {
        segmenter.push(block.samples)
        const now = performance.now()
        if (onActivity && now - lastActivityAt >= 100) {
          let sum = 0
          for (const sample of block.samples) sum += sample * sample
          onActivity(Math.min(1, Math.sqrt(sum / Math.max(1, block.samples.length)) * 6))
          lastActivityAt = now
        }
      }
    }
    source.connect(node)
    node.connect(context.destination)
    for (const track of stream.getTracks()) track.onended = () => { void cleanup(); onEnded() }
    await context.resume()
    const supported = mode === 'meeting' && Boolean((navigator.mediaDevices.getSupportedConstraints?.() as MediaTrackSupportedConstraints & { suppressLocalAudioPlayback?: boolean } | undefined)?.suppressLocalAudioPlayback)
    return {
      originalMuteSupported: supported,
      pause: () => { paused = true; segmenter.reset(); onActivity?.(0) },
      resume: () => { if (!stopped) { if (captureStartedAtMs === null) captureStartedAtMs = performance.now(); paused = false } },
      stop: cleanup,
      setOriginalMuted: async (muted) => {
        if (!supported || stopped) return false
        try {
          await audioTrack.applyConstraints({ suppressLocalAudioPlayback: muted } as MediaTrackConstraints)
          return (audioTrack.getSettings() as MediaTrackSettings & { suppressLocalAudioPlayback?: boolean }).suppressLocalAudioPlayback === muted
        } catch { return false }
      },
    }
  } catch (cause) {
    await cleanup()
    if (cause instanceof DOMException && cause.name === 'NotAllowedError') throw new Error(mode === 'meeting' ? 'Tab sharing was denied. Choose the meeting tab and allow audio sharing.' : 'Microphone access was denied. Allow microphone access in browser site settings and try again.')
    throw cause
  }
}
