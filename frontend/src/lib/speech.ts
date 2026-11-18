import type { Language } from './types'
import { languageByCode } from './languageRegistry'
import { voiceForLanguage } from './voices'

export function speak(text: string, language: Language, rate: number): void {
  if (!('speechSynthesis' in window)) throw new Error('Audio playback is not available in this browser.')
  const voice = voiceForLanguage(window.speechSynthesis.getVoices(), language)
  if (!voice) throw new Error(`No ${languageByCode(language).name} voice is available in this browser. Translation text is still available.`)
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = languageByCode(language).speech_tag
  utterance.voice = voice
  utterance.rate = rate
  window.speechSynthesis.speak(utterance)
}
