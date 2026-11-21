import { afterEach, expect, it, vi } from 'vitest'
import { AutoSpeechQueue } from '../lib/autoSpeechQueue'
import { encodePcmWav } from '../lib/audio'

afterEach(() => vi.unstubAllGlobals())

class Utterance {
  lang = ''
  voice: SpeechSynthesisVoice | null = null
  rate = 1
  onstart: (() => void) | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public text: string) {}
}

function synth(languages: string[]) {
  const spoken: Utterance[] = []
  const engine = {
    getVoices: () => languages.map((lang) => ({ lang, name: lang, voiceURI: lang } as SpeechSynthesisVoice)),
    speak: (item: Utterance) => { spoken.push(item) },
    pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
  } as unknown as SpeechSynthesis
  vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
  return { engine, spoken }
}

it('falls back in phrase order to matching Hindi and Marathi browser voices after Azure errors', () => {
  const { engine, spoken } = synth(['hi-IN', 'mr-IN'])
  const providers: string[] = []
  const queue = new AutoSpeechQueue(engine, (provider) => providers.push(provider), vi.fn(), vi.fn())
  expect(queue.addResult(1, 'नमस्ते', 'hi', 1)).toBe(true)
  expect(queue.addResult(2, 'नमस्कार', 'mr', 1)).toBe(true)
  queue.speechError(2)
  expect(spoken).toHaveLength(0)
  queue.speechError(1)
  queue.addAudio(1, 'malformed-late-audio')
  expect(spoken).toHaveLength(1)
  expect(spoken[0].lang).toBe('hi-IN')
  spoken[0].onstart?.()
  spoken[0].onend?.()
  expect(spoken).toHaveLength(2)
  expect(spoken[1].lang).toBe('mr-IN')
  spoken[1].onstart?.()
  spoken[1].onend?.()
  expect(providers).toEqual(['browser', 'browser'])
  queue.stop()
})

it('shows captions-only when no matching voice exists and cancels on stop', () => {
  const { engine, spoken } = synth(['en-US'])
  const provider = vi.fn()
  const queue = new AutoSpeechQueue(engine, provider, vi.fn(), vi.fn())
  queue.addResult(1, 'नमस्कार', 'mr', 1)
  queue.disableAzure()
  expect(spoken).toHaveLength(0)
  expect(provider).toHaveBeenLastCalledWith('captions', expect.stringContaining('No matching browser voice'))
  queue.addResult(2, 'नमस्ते', 'hi', 1)
  queue.stop()
  expect(engine.cancel).toHaveBeenCalled()
  expect(queue.addResult(3, 'ignored', 'hi', 1)).toBe(false)
})

it('plays Azure WAV first and falls back to browser only if Azure never started', () => {
  const { engine, spoken } = synth(['hi-IN'])
  const players: Player[] = []
  class Player {
    onplaying: (() => void) | null = null
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    play = vi.fn().mockResolvedValue(undefined)
    pause = vi.fn()
    removeAttribute = vi.fn()
    load = vi.fn()
    constructor(_url: string) { players.push(this) }
  }
  vi.stubGlobal('Audio', Player)
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() })
  const wav = new Uint8Array(encodePcmWav(new Float32Array(2400).fill(0.1), 24_000, 24_000))
  const encoded = btoa(String.fromCharCode(...wav))
  const provider = vi.fn()
  const queue = new AutoSpeechQueue(engine, provider, vi.fn(), vi.fn())
  queue.addResult(1, 'नमस्ते', 'hi', 1)
  queue.addResult(2, 'फिर मिलेंगे', 'hi', 1)
  queue.addAudio(1, encoded)
  expect(players).toHaveLength(1)
  expect(spoken).toHaveLength(0)
  players[0].onplaying?.()
  expect(provider).toHaveBeenCalledWith('azure')
  players[0].onended?.()
  queue.addAudio(2, encoded)
  expect(players).toHaveLength(2)
  players[1].onerror?.()
  expect(spoken).toHaveLength(1)
  spoken[0].onstart?.()
  expect(provider).toHaveBeenLastCalledWith('browser')
  queue.stop()
  expect(spoken[0].onend).toBeNull()
})
