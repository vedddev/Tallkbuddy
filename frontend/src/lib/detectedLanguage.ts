import { languageRegistry } from './languageRegistry'

/** Labels provider metadata without inferring a language from transcript text. */
export function detectedLanguageLabel(code: string | null | undefined, source?: 'stt' | 'unknown'): string {
  if (!code || source === 'unknown') return 'Unknown language'
  const registered = languageRegistry.find((entry) => entry.code === code)
  if (registered) return registered.name
  if (!/^[a-z]{2}$/.test(code)) return 'Unknown language'
  try {
    const label = new Intl.DisplayNames(['en'], { type: 'language' }).of(code)
    return label && label.toLowerCase() !== code ? label : 'Unknown language'
  } catch { return code.toUpperCase() }
}

export function detectedLanguageTag(code: string | null | undefined): string | undefined {
  const registered = languageRegistry.find((entry) => entry.code === code)
  if (registered) return registered.speech_tag
  return code && /^[a-z]{2}$/.test(code) ? code : undefined
}
