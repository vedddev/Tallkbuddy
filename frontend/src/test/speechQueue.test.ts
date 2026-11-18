import { afterEach, expect, it, vi } from 'vitest'
import { SpeechQueue } from '../lib/speechQueue'
import { languageRegistry } from '../lib/languageRegistry'
import { voiceForLanguage } from '../lib/voices'

afterEach(() => vi.unstubAllGlobals())

function voice(lang: string): SpeechSynthesisVoice {
  return { lang, name: `${lang} voice`, default: false, localService: true, voiceURI: lang } as SpeechSynthesisVoice
}

class FakeUtterance {
  lang = ''
  voice: SpeechSynthesisVoice | null = null
  rate = 1
  onstart: (() => void) | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public text: string) {}
}

it.each(languageRegistry)('maps $code speech to an installed matching voice', (entry) => {
  expect(voiceForLanguage([voice('en-US'), voice(entry.speech_tag)], entry.code)?.lang).toBe(entry.speech_tag)
  const spoken: SpeechSynthesisUtterance[] = []
  const synth = {
    getVoices: () => [voice('en-US'), voice(entry.speech_tag)],
    speak: (utterance: SpeechSynthesisUtterance) => spoken.push(utterance),
    pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
  } as unknown as SpeechSynthesis
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  const queue = new SpeechQueue(synth)
  expect(queue.enqueue(1, 'Translated phrase', entry.code, 1)).toBe('queued')
  expect(spoken[0].lang).toBe(entry.speech_tag)
  expect(spoken[0].voice?.lang).toBe(entry.speech_tag)
})

it('never substitutes an unrelated voice, including Cantonese for Mandarin', () => {
  expect(voiceForLanguage([voice('en-US')], 'ja')).toBeNull()
  expect(voiceForLanguage([voice('zh-HK'), voice('en-US')], 'zh-CN')).toBeNull()
  expect(voiceForLanguage([voice('cmn-Hans-CN')], 'zh-CN')?.lang).toBe('cmn-Hans-CN')
})

it('plays translations once and in order without overlap', () => {
  const spoken: SpeechSynthesisUtterance[] = []
  const synth = {
    getVoices: () => [voice('hi-IN'), voice('mr-IN')],
    speak: vi.fn((utterance: SpeechSynthesisUtterance) => spoken.push(utterance)),
    pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
  } as unknown as SpeechSynthesis
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  const onStatus = vi.fn()
  const queue = new SpeechQueue(synth, vi.fn(), onStatus)
  expect(queue.enqueue(1, 'नमस्ते', 'hi', 1.1)).toBe('queued')
  expect(queue.enqueue(1, 'duplicate', 'hi', 1)).toBe('duplicate')
  expect(queue.enqueue(2, 'पुढे', 'mr', 1)).toBe('queued')
  expect(spoken).toHaveLength(1)
  expect(spoken[0].lang).toBe('hi-IN')
  expect(spoken[0].voice?.lang).toBe('hi-IN')
  expect(onStatus).toHaveBeenCalledWith('playing', 1)
  queue.pause()
  expect(onStatus).toHaveBeenLastCalledWith('paused', 1)
  spoken[0].onend?.(new Event('end') as SpeechSynthesisEvent)
  expect(spoken).toHaveLength(1)
  queue.resume()
  expect(spoken).toHaveLength(2)
  expect(spoken[1].voice?.lang).toBe('mr-IN')
  queue.stop()
  expect(onStatus).toHaveBeenLastCalledWith('idle', 0)
  expect(synth.cancel).toHaveBeenCalledOnce()
})

it('skips speech when the requested language voice is missing', () => {
  const synth = { getVoices: () => [voice('en-US')], speak: vi.fn(), pause: vi.fn(), resume: vi.fn(), cancel: vi.fn() } as unknown as SpeechSynthesis
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  const queue = new SpeechQueue(synth)
  expect(queue.enqueue(1, 'こんにちは', 'ja', 1)).toBe('voice_unavailable')
  expect(synth.speak).not.toHaveBeenCalled()
})

it('measures browser preparation, queue wait, and actual speech start separately', () => {
  const spoken: SpeechSynthesisUtterance[] = []
  const synth = {
    getVoices: () => [voice('hi-IN')],
    speak: (utterance: SpeechSynthesisUtterance) => spoken.push(utterance),
    pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
  } as unknown as SpeechSynthesis
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  const clock = vi.spyOn(performance, 'now')
  const events = vi.fn()
  const queue = new SpeechQueue(synth, vi.fn(), vi.fn(), events)
  clock.mockReturnValue(100)
  queue.enqueue(1, 'First', 'hi', 1)
  clock.mockReturnValue(120)
  queue.enqueue(2, 'Second', 'hi', 1)
  clock.mockReturnValue(160)
  spoken[0].onstart?.(new Event('start') as SpeechSynthesisEvent)
  expect(events).toHaveBeenCalledWith({ type: 'started', chunkId: 1, queueWaitMs: 0, playbackStartDelayMs: 60, startedAtMs: 160 })
  clock.mockReturnValue(200)
  spoken[0].onend?.(new Event('end') as SpeechSynthesisEvent)
  clock.mockReturnValue(250)
  spoken[1].onstart?.(new Event('start') as SpeechSynthesisEvent)
  expect(events).toHaveBeenCalledWith({ type: 'started', chunkId: 2, queueWaitMs: 80, playbackStartDelayMs: 50, startedAtMs: 250 })
  expect(events.mock.calls.filter(([event]) => event.type === 'prepared')).toHaveLength(2)
  queue.stop()
  clock.mockRestore()
})
