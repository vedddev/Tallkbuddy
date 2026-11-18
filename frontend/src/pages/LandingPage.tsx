import { ArrowRight, AudioLines, Captions, LockKeyhole, Moon, Sun, Volume2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

const features = [
  { icon: Captions, title: 'Follow complete phrases', text: 'Read original and translated captions while you listen to a shared browser tab.' },
  { icon: Volume2, title: 'Hear translations locally', text: 'Play translated speech on this device when a matching browser voice is available.' },
  { icon: LockKeyhole, title: 'Choose what you save', text: 'History is off by default. Opt in to save text and delete it whenever you choose.' },
]

export function LandingPage() {
  const { user } = useAuth()
  const { theme, toggle } = useTheme()
  return <div className="min-h-screen bg-canvas text-foreground">
    <header className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-5 sm:px-8">
      <Logo />
      <nav aria-label="Public navigation" className="flex items-center gap-2">
        <button type="button" onClick={toggle} className="icon-btn" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}>{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button>
        <Link to={user ? '/overview' : '/login'} className="btn-secondary">{user ? 'Workspace' : 'Log in'}</Link>
      </nav>
    </header>
    <main>
      <section className="mx-auto grid max-w-6xl min-w-0 items-center gap-10 px-4 py-12 sm:px-8 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,.88fr)] lg:gap-16 lg:py-28">
        <div className="min-w-0">
          <p className="eyebrow">LOCAL MEETING INTERPRETATION</p>
          <h1 className="mt-4 max-w-2xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl xl:text-6xl">A conversation without borders.</h1>
          <p className="mt-5 max-w-xl text-base leading-7 text-muted">Share a browser tab with permission, follow complete phrases in translation, and hear them on your device when a voice is available.</p>
          <div className="mt-8 flex flex-wrap items-center gap-3"><Link to={user ? '/overview' : '/register'} className="btn-primary">{user ? 'Open workspace' : 'Get started'}<ArrowRight size={16} aria-hidden="true" /></Link><Link to={user ? '/translate' : '/login'} className="btn-secondary">Text translation</Link></div>
          <p className="mt-6 text-xs leading-5 text-muted">Local playback does not broadcast translated speech into Google Meet.</p>
        </div>
        <div className="panel min-w-0 overflow-hidden" aria-label="Illustration of translation panels">
          <div className="flex items-center justify-between gap-2 border-b border-line px-5 py-4"><span className="flex items-center gap-2 text-sm font-semibold"><AudioLines size={17} className="text-accent" />Meeting Interpreter</span><span className="rounded-md bg-raised px-2 py-1 text-xs text-muted">Example</span></div>
          <div className="grid gap-3 p-4 sm:p-5"><div className="rounded-lg border border-line p-4"><p className="text-xs font-medium text-muted">Original · English</p><p className="mt-2 break-words text-sm leading-6">It's wonderful to finally meet you.</p></div><div className="rounded-lg border border-line bg-raised p-4"><p className="text-xs font-medium text-accent">Translated · Hindi</p><p lang="hi-IN" className="mt-2 break-words text-base leading-7">आखिरकार आपसे मिलकर बहुत अच्छा लगा।</p></div><p className="text-xs leading-5 text-muted">Illustrative text only. No meeting is connected.</p></div>
        </div>
      </section>
      <section className="border-t border-line bg-sidebar"><div className="mx-auto max-w-6xl px-4 py-14 sm:px-8 sm:py-20"><p className="eyebrow">BUILT FOR CONVERSATION</p><h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Translate with clarity and control.</h2><div className="mt-8 grid gap-4 md:grid-cols-3">{features.map(({ icon: Icon, title, text }) => <article key={title} className="panel min-w-0 p-5"><span className="grid h-9 w-9 place-items-center rounded-lg bg-raised text-accent"><Icon size={18} /></span><h3 className="mt-5 text-sm font-semibold">{title}</h3><p className="mt-2 text-sm leading-6 text-muted">{text}</p></article>)}</div></div></section>
    </main>
    <footer className="mx-auto flex max-w-6xl flex-wrap justify-between gap-3 px-4 py-6 text-xs text-muted sm:px-8"><span>TalkBuddy · Translation with your permission</span><span>History off by default</span></footer>
  </div>
}
