import { languageByCode, type LanguageCode } from './languageRegistry'

function normalizeTag(tag: string): string {
  return tag.trim().replaceAll('_', '-').toLowerCase()
}

/** Select a voice for the requested language without falling back to another language. */
export function voiceForLanguage(voices: SpeechSynthesisVoice[], language: LanguageCode): SpeechSynthesisVoice | null {
  const expected = normalizeTag(languageByCode(language).speech_tag)
  const exact = voices.find((voice) => normalizeTag(voice.lang) === expected)
  if (exact) return exact

  if (language === 'zh-CN') {
    const mandarinTags = new Set(['zh-hans-cn', 'zh-hans', 'cmn-cn', 'cmn-hans-cn', 'cmn-hans'])
    return voices.find((voice) => mandarinTags.has(normalizeTag(voice.lang))) || null
  }

  const primary = expected.split('-')[0]
  return voices.find((voice) => {
    const tag = normalizeTag(voice.lang)
    return tag === primary || tag.startsWith(`${primary}-`)
  }) || null
}
