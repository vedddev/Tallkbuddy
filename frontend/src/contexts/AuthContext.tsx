import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError } from '../lib/api'
import type { User } from '../lib/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    api.me().then((current) => { if (mounted) setUser(current) }).catch((error: unknown) => {
      if (mounted && !(error instanceof ApiError && error.status === 401)) console.warn('Session check failed')
    }).finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [])

  const login = useCallback(async (email: string, password: string) => setUser(await api.login(email, password)), [])
  const register = useCallback(async (name: string, email: string, password: string) => { await api.register(name, email, password) }, [])
  const logout = useCallback(async () => { await api.logout(); setUser(null) }, [])

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider is required')
  return value
}
