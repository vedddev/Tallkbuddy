import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, AudioLines, Clock3, Languages, Mic2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeading } from '../components/PageHeading'
import { Button, Card, EmptyState, ErrorMessage, LoadingState, StatusIndicator } from '../components/ui/Primitives'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../lib/api'
import { languageByCode } from '../lib/languageRegistry'
import type { TranslationSession } from '../lib/types'

function sessionDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function OverviewPage() {
  const { user } = useAuth()
  const [sessions, setSessions] = useState<TranslationSession[] | null>(null)
  const [historyError, setHistoryError] = useState('')
  const [apiReachable, setApiReachable] = useState<boolean | null>(null)
  const [retry, setRetry] = useState(0)
  const reload = useCallback(() => setRetry((value) => value + 1), [])

  useEffect(() => {
    let mounted = true
    setSessions(null); setHistoryError(''); setApiReachable(null)
    void api.history(0, 5).then((page) => { if (mounted) setSessions(page.items) })
      .catch(() => { if (mounted) setHistoryError('Could not load recent sessions. Retry when your connection is available.') })
    void api.health().then((response) => { if (mounted) setApiReachable(response.status === 'ok') })
      .catch(() => { if (mounted) setApiReachable(false) })
    return () => { mounted = false }
  }, [retry])

  return <>
    <PageHeading eyebrow="OVERVIEW" title={`Welcome${user?.name ? `, ${user.name.split(' ')[0]}` : ''}`} description="Choose a translation workspace or pick up a session you saved." action={<StatusIndicator label={apiReachable === null ? 'Checking API' : apiReachable ? 'API reachable' : 'API unavailable'} tone={apiReachable === null ? 'neutral' : apiReachable ? 'success' : 'danger'} />} />
    <div className="grid gap-4 md:grid-cols-2"><Card className="flex min-w-0 flex-col p-5"><span className="grid h-10 w-10 place-items-center rounded-lg bg-raised text-accent"><AudioLines size={20} /></span><h2 className="mt-5 text-base font-semibold">Live Meeting</h2><p className="mt-2 flex-1 text-sm leading-6 text-muted">Interpret a browser tab you choose to share, with live captions and local speech playback.</p><Link to="/meeting" className="btn-primary mt-5 self-start">Start Live Meeting <ArrowRight size={16} /></Link></Card>
      <Card className="flex min-w-0 flex-col p-5"><span className="grid h-10 w-10 place-items-center rounded-lg bg-raised text-accent"><Languages size={20} /></span><h2 className="mt-5 text-base font-semibold">Text Translation</h2><p className="mt-2 flex-1 text-sm leading-6 text-muted">Translate a written phrase into any enabled language.</p><Link to="/translate" className="btn-secondary mt-5 self-start">Open Text Translation <ArrowRight size={16} /></Link></Card></div>
    <div className="mt-4 flex items-center gap-2 text-xs text-muted"><Mic2 size={15} /><span>Need microphone translation?</span><Link className="font-medium text-accent underline" to="/workspace">Open the existing microphone workspace</Link></div>
    <Card className="mt-7 overflow-hidden"><div className="flex items-center justify-between border-b border-line px-5 py-4"><div><h2 className="text-sm font-semibold">Recent saved sessions</h2><p className="mt-1 text-xs text-muted">Only sessions you chose to save appear here.</p></div><Link to="/history" className="text-xs font-medium text-accent hover:underline">View history</Link></div>
      {historyError ? <div className="space-y-3 p-5"><ErrorMessage message={historyError} /><Button onClick={reload}>Retry</Button></div> : sessions === null ? <LoadingState label="Loading recent sessions…" /> : sessions.length === 0 ? <EmptyState title="No saved sessions" description="History is off by default. Enable it in Settings and opt in for a translation when you want to keep it." action={<Link className="btn-secondary" to="/settings">History settings</Link>} /> : <ul className="divide-y divide-line">{sessions.map((session) => <li key={session.id}><Link to={`/history/${session.id}`} className="flex min-w-0 items-center gap-3 px-5 py-4 transition-colors duration-150 hover:bg-raised"><Clock3 size={17} className="shrink-0 text-muted" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{session.title || 'Untitled session'}</span><span className="mt-1 block truncate text-xs text-muted">{session.source_language === 'auto' ? 'Auto detect' : languageByCode(session.source_language).name} → {languageByCode(session.target_language).name}</span></span><time dateTime={session.started_at} className="shrink-0 text-xs text-muted">{sessionDate(session.started_at)}</time></Link></li>)}</ul>}
    </Card>
    <p className="mt-4 text-xs text-muted">API status checks application reachability only. It does not verify database or AI provider availability.</p>
  </>
}
