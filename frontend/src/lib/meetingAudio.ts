import { captureWorkletCode, encodePcmWav } from './audio'
import type { CaptureTiming } from './latency'

const OUTPUT_RATE = 16_000
const MAX_WAV_BYTES = 1_000_000

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

  constructor(
    private sampleRate: number,
    private onPhrase: (samples: Float32Array, timing: CaptureTiming) => void,
    private onDrop: () => void = () => undefined,
  ) {}

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
      const maxPreroll = Math.floor(this.sampleRate * 0.25)
      while (this.prerollSamples > maxPreroll && this.preroll.length > 1) {
        this.prerollSamples -= this.preroll.shift()!.length
      }
      this.candidateSamples = voiced ? this.candidateSamples + block.length : 0
      if (this.candidateSamples < this.sampleRate * 0.12) return
      this.active = true
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
    if (this.trailingSilence >= this.sampleRate * 0.7) {
      this.finish()
    } else if (this.segmentSamples >= this.sampleRate * 12) {
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
  }

  private finish(): void {
    if (this.voicedSamples < this.sampleRate * 0.6) { this.reset(); return }
    // The phrase boundary is detected after trailing silence. Estimate the
    // speech end on this browser's monotonic clock without changing VAD.
    const speechEndAtMs = performance.now() - this.trailingSilence / this.sampleRate * 1000
    const keep = Math.min(this.segmentSamples, this.segmentSamples - this.trailingSilence + Math.floor(this.sampleRate * 0.15))
    const joined = new Float32Array(keep)
    let cursor = 0
    for (const block of this.segment) {
      const take = Math.min(block.length, keep - cursor)
      if (take <= 0) break
      joined.set(block.subarray(0, take), cursor)
      cursor += take
    }
    this.reset()
    this.onPhrase(joined, { speechEndAtMs, captureDurationMs: joined.length / this.sampleRate * 1000 })
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
): Promise<MeetingCapture> {
  if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('Tab audio capture is unavailable in this browser or context.')
  // This must run directly from the Start button click, before network requests.
  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'browser' },
      audio: { suppressLocalAudioPlayback: muteOriginal },
      selfBrowserSurface: 'exclude',
    } as DisplayMediaStreamOptions)
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'NotAllowedError') throw new Error('Tab sharing was denied. Choose the meeting tab and allow audio sharing.')
    throw cause
  }
  let context: AudioContext | null = null
  let moduleUrl: string | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let node: AudioWorkletNode | null = null
  let stopped = false
  let paused = true
  let lastActivityAt = -Infinity
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
    if (!audioTrack) throw new Error('No tab audio was shared. Select a browser tab and enable Share tab audio.')
    const displaySurface = stream.getVideoTracks()[0]?.getSettings?.().displaySurface
    if (displaySurface && displaySurface !== 'browser') throw new Error('Select the meeting browser tab, not a screen or window.')
    context = new AudioContext()
    if (!context.audioWorklet) throw new Error('This browser does not support AudioWorklet capture.')
    const segmenter = new PhraseSegmenter(context.sampleRate, (samples, timing) => {
      const wav = encodePcmWav(samples, context!.sampleRate, OUTPUT_RATE)
      if (wav.byteLength <= MAX_WAV_BYTES) onChunk(wav, timing)
      else onDrop()
    }, onDrop)
    moduleUrl = URL.createObjectURL(new Blob([captureWorkletCode], { type: 'text/javascript' }))
    await context.audioWorklet.addModule(moduleUrl)
    source = context.createMediaStreamSource(stream)
    node = new AudioWorkletNode(context, 'talkbuddy-capture')
    node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!stopped && !paused && event.data instanceof Float32Array) {
        segmenter.push(event.data)
        const now = performance.now()
        if (onActivity && now - lastActivityAt >= 100) {
          let sum = 0
          for (const sample of event.data) sum += sample * sample
          onActivity(Math.min(1, Math.sqrt(sum / Math.max(1, event.data.length)) * 6))
          lastActivityAt = now
        }
      }
    }
    source.connect(node)
    node.connect(context.destination)
    for (const track of stream.getTracks()) track.onended = () => { void cleanup(); onEnded() }
    await context.resume()
    const supported = Boolean((navigator.mediaDevices.getSupportedConstraints?.() as MediaTrackSupportedConstraints & { suppressLocalAudioPlayback?: boolean } | undefined)?.suppressLocalAudioPlayback)
    return {
      originalMuteSupported: supported,
      pause: () => { paused = true; segmenter.reset(); onActivity?.(0) },
      resume: () => { if (!stopped) paused = false },
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
    if (cause instanceof DOMException && cause.name === 'NotAllowedError') throw new Error('Tab sharing was denied. Choose the meeting tab and allow audio sharing.')
    throw cause
  }
}
