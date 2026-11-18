import type { Language, Page, Preferences, SessionDetail, TranslationSession, User } from './types'

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim()
export const apiBase = configuredBase || window.location.origin

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export function csrfToken(cookieString: string): string | null {
  const pair = cookieString.split(';').map((part) => part.trim()).find((part) => part.startsWith('talkbuddy_csrf='))
  return pair ? decodeURIComponent(pair.slice('talkbuddy_csrf='.length)) : null
}

type RequestOptions = { method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'; body?: unknown; headers?: Record<string, string> }

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method || 'GET'
  const headers: Record<string, string> = { ...options.headers }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && path !== '/api/auth/login' && path !== '/api/auth/register') {
    const token = csrfToken(document.cookie)
    if (!token) throw new ApiError(403, 'Your security cookie is missing. Sign in again and retry.')
    headers['X-CSRF-Token'] = token
  }
  let response: Response
  try {
    response = await fetch(new URL(path, apiBase), {
      method,
      credentials: 'include',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'Cannot reach TalkBuddy. Check your connection and try again.')
  }
  if (response.status === 204) return undefined as T
  const content = await response.json().catch(() => null) as { detail?: unknown } | null
  if (!response.ok) {
    const detail = content?.detail
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg).filter(Boolean).join('. ')
        : response.status === 429 ? 'Too many attempts. Please wait and try again.' : 'Something went wrong. Please try again.'
    throw new ApiError(response.status, message || 'Something went wrong. Please try again.')
  }
  return content as T
}

export const api = {
  health: () => apiRequest<{ status: 'ok' }>('/api/health'),
  me: () => apiRequest<User>('/api/auth/me'),
  login: (email: string, password: string) => apiRequest<User>('/api/auth/login', { method: 'POST', body: { email, password } }),
  register: (name: string, email: string, password: string) => apiRequest<User>('/api/auth/register', { method: 'POST', body: { name, email, password } }),
  logout: () => apiRequest<{ message: string }>('/api/auth/logout', { method: 'POST' }),
  preferences: () => apiRequest<Preferences>('/api/preferences'),
  updatePreferences: (updates: Partial<Preferences>) => apiRequest<Preferences>('/api/preferences', { method: 'PATCH', body: updates }),
  createSession: (source_language: string, target_language: Language) => apiRequest<TranslationSession>('/api/translation-sessions', { method: 'POST', body: { source_language, target_language } }),
  endSession: (id: string) => apiRequest<TranslationSession>(`/api/translation-sessions/${id}/end`, { method: 'POST' }),
  history: (offset = 0, limit = 20) => apiRequest<Page<TranslationSession>>(`/api/history?offset=${offset}&limit=${limit}&order=newest`),
  session: (id: string, offset = 0, limit = 50) => apiRequest<SessionDetail>(`/api/history/${id}?offset=${offset}&limit=${limit}&order=oldest`),
  deleteSession: (id: string) => apiRequest<void>(`/api/history/${id}`, { method: 'DELETE' }),
  clearHistory: () => apiRequest<{ deleted_sessions: number }>('/api/history', { method: 'DELETE' }),
  translateText: (text: string, target_language: Language, session_id?: string) => apiRequest<{
    original_text: string; translated_text: string; target_language: Language; saved?: boolean; message_id?: string
  }>('/api/ai/translate', {
    method: 'POST',
    headers: session_id ? { 'Idempotency-Key': crypto.randomUUID() } : undefined,
    body: { text, target_language, save_history: Boolean(session_id), ...(session_id ? { session_id } : {}) },
  }),
}
