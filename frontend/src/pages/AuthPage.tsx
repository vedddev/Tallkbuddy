import { useState, type FormEvent } from 'react'
import { ArrowRight, AudioLines, Eye, EyeOff, Moon, Sun } from 'lucide-react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { Button, ErrorMessage, Input } from '../components/ui/Primitives'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { user, login, register } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (user) return <Navigate to="/overview" replace />

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError('')
    try {
      if (mode === 'register') {
        await register(name.trim(), email.trim(), password)
        navigate('/login', { state: { registered: true } })
      } else {
        await login(email.trim(), password)
        navigate('/overview')
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not continue. Please try again.')
    } finally { setBusy(false) }
  }

  return <div className="min-h-screen bg-canvas text-foreground">
    <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-5 sm:px-8">
      <Logo />
      <button type="button" onClick={toggle} className="icon-btn" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} title={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}>{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button>
    </header>
    <main className="mx-auto grid w-full max-w-6xl gap-8 px-4 pb-12 pt-6 sm:px-8 lg:min-h-[calc(100vh-132px)] lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:items-center lg:gap-16 lg:py-10">
      <section className="hidden min-w-0 lg:block">
        <div className="mb-7 inline-flex h-11 w-11 items-center justify-center rounded-lg border border-line bg-surface text-accent"><AudioLines size={22} /></div>
        <p className="eyebrow">TALKBUDDY</p>
        <h2 className="mt-3 max-w-xl text-4xl font-semibold leading-tight tracking-tight xl:text-5xl">Understand the conversation, wherever it happens.</h2>
        <p className="mt-5 max-w-lg text-base leading-7 text-muted">Translate complete phrases, follow live meetings locally, and keep only the history you choose to save.</p>
        <p className="mt-10 border-l-2 border-accent pl-4 text-sm leading-6 text-muted">Meeting interpretation plays on your device. Broadcasting into a meeting is not available yet.</p>
      </section>
      <section className="panel min-w-0 p-5 sm:p-8" aria-labelledby="auth-title">
        <p className="eyebrow">{mode === 'login' ? 'WELCOME BACK' : 'GET STARTED'}</p>
        <h1 id="auth-title" className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{mode === 'login' ? 'Good to have you back.' : 'Create your account.'}</h1>
        <p className="mt-2 text-sm leading-6 text-muted">{mode === 'login' ? 'Sign in to continue to your workspace.' : 'Start translating with a private account.'}</p>
        {mode === 'login' && location.state?.registered && <p role="status" className="mt-5 rounded-lg border border-[var(--color-success)] bg-[var(--color-success-surface)] px-4 py-3 text-sm text-[var(--color-success)]">Account created. Sign in to begin.</p>}
        {error && <div className="mt-5"><ErrorMessage message={error} /></div>}
        <form onSubmit={(event) => void submit(event)} className="mt-6 space-y-5">
          {mode === 'register' && <Input id="auth-name" label="Your name" value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" minLength={2} maxLength={255} required disabled={busy} placeholder="Your name" />}
          <Input id="auth-email" label="Email address" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required disabled={busy} placeholder="you@example.com" />
          <div className="grid gap-1.5"><label htmlFor="auth-password" className="text-sm font-medium">Password</label><div className="relative"><input id="auth-password" className="field w-full pr-12" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={mode === 'register' ? 12 : undefined} maxLength={128} required disabled={busy} aria-describedby={mode === 'register' ? 'password-hint' : undefined} placeholder={mode === 'register' ? 'At least 12 characters' : 'Enter your password'} /><button type="button" className="icon-btn absolute right-1 top-1/2 -translate-y-1/2" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} disabled={busy}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>{mode === 'register' && <p id="password-hint" className="text-xs text-muted">Use at least 12 characters.</p>}</div>
          <Button type="submit" variant="primary" busy={busy} className="w-full">{busy ? 'Please wait...' : mode === 'login' ? 'Sign in' : 'Create account'}{!busy && <ArrowRight size={16} aria-hidden="true" />}</Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted">{mode === 'login' ? 'New to TalkBuddy?' : 'Already have an account?'} <Link className="font-semibold text-accent underline-offset-4 hover:underline" to={mode === 'login' ? '/register' : '/login'}>{mode === 'login' ? 'Create an account' : 'Sign in'}</Link></p>
      </section>
    </main>
    <footer className="mx-auto max-w-6xl px-4 pb-6 text-xs text-muted sm:px-8">TalkBuddy · Your history stays off until you opt in.</footer>
  </div>
}
