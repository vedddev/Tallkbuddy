import registry from '../../../shared/languages.json'

export type LanguageCode = 'en' | 'hi' | 'mr' | 'es' | 'de' | 'fr' | 'ja' | 'ru' | 'zh-CN' | 'ko'
export type ApiLanguage = LanguageCode

export interface LanguageDefinition {
  code: LanguageCode
  name: string
  native: string
  whisper_code: string
  speech_tag: string
  api_enabled: boolean
}

/** Shared registry for codes accepted by the FastAPI translation APIs. */
export const languageRegistry = registry as LanguageDefinition[]
export const apiLanguages = languageRegistry.filter((entry): entry is LanguageDefinition & { code: ApiLanguage } => entry.api_enabled)

export function languageByCode(code: LanguageCode): LanguageDefinition {
  const entry = languageRegistry.find((item) => item.code === code)
  if (!entry) throw new Error(`Unknown language code: ${code}`)
  return entry
}
