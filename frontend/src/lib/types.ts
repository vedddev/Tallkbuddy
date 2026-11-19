import { apiLanguages, type ApiLanguage } from './languageRegistry'

export type Language = ApiLanguage
export type SourceLanguage = Language | 'auto'

export const languages: { code: Language; name: string; native: string; speech: string }[] =
  apiLanguages.map((entry) => ({ code: entry.code, name: entry.name, native: entry.native, speech: entry.speech_tag }))

export interface User {
  id: string
  name: string
  email: string
  is_active: boolean
  email_verified: boolean
  created_at: string
}

export interface Preferences {
  source_language: SourceLanguage
  target_language: Language
  speech_rate: number
  save_history_enabled: boolean
}

export interface TranslationSession {
  id: string
  title: string | null
  source_language: SourceLanguage
  target_language: Language
  started_at: string
  ended_at: string | null
}

export interface TranslationMessage {
  id: string
  original_text: string
  translated_text: string
  detected_language: Language | null
  created_at: string
}

export interface Page<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}

export interface SessionDetail {
  session: TranslationSession
  messages: Page<TranslationMessage>
}

export type SocketMessage =
  | { type: 'ready'; target_language: Language; source_language: Language | null; audio_format: 'wav' }
  | { type: 'processing'; chunk_id: number }
  | {
      type: 'result'; chunk_id: number; original: string; translated: string
      detected_language: Language | null; target_language: Language; processing_time_ms: number
      transcription_time_ms?: number; translation_time_ms?: number
      saved?: boolean; message_id?: string
    }
  | { type: 'error'; code: string; message: string; recoverable: boolean }
  | { type: 'speech_audio'; chunk_id: number; audio_format: 'wav'; audio_base64: string; preparation_time_ms?: number }
  | { type: 'speech_error'; chunk_id: number; code: string; message: string }
