import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ChevronLeft, ChevronRight, Clock3, Trash2, Volume2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageHeading } from '../components/PageHeading'
import { Button, Card, EmptyState, ErrorMessage, Input, LoadingState, Select } from '../components/ui/Primitives'
import { api } from '../lib/api'
import { apiLanguages, languageByCode } from '../lib/languageRegistry'
import { speak } from '../lib/speech'
import type { Page, Preferences, SessionDetail, TranslationSession } from '../lib/types'

function dateLabel(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function sourceName(code: TranslationSession['source_language']) { return code === 'auto' ? 'Auto detect' : languageByCode(code).name }

export function HistoryPage() {
  const [page, setPage] = useState<Page<TranslationSession> | null>(null)
  const [offset, setOffset] = useState(0)
  const [retry, setRetry] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [targetFilter, setTargetFilter] = useState('')

  useEffect(() => {
    let mounted = true
    setBusy(true); setError(''); setPage(null)
    void api.history(offset, 20).then((value) => { if (mounted) setPage(value) })
      .catch((cause: unknown) => { if (mounted) setError(cause instanceof Error ? cause.message : 'Could not load history.') })
      .finally(() => { if (mounted) setBusy(false) })
    return () => { mounted = false }
  }, [offset, retry])

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return (page?.items || []).filter((session) => {
      if (sourceFilter && session.source_language !== sourceFilter) return false
      if (targetFilter && session.target_language !== targetFilter) return false
      const searchable = `${session.title || ''} ${sourceName(session.source_language)} ${session.source_language} ${languageByCode(session.target_language).name} ${session.target_language}`.toLocaleLowerCase()
      return searchable.includes(needle)
    })
  }, [page, query, sourceFilter, targetFilter])

  const clear = async () => {
    if (!window.confirm('Delete all saved translation sessions and messages? This cannot be undone.')) return
    setBusy(true); setError('')
    try { await api.clearHistory(); setOffset(0); setRetry((value) => value + 1) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not clear history.'); setBusy(false) }
  }

  return <>
    <PageHeading eyebrow="HISTORY" title="Saved sessions" description="Only translations you chose to save appear here. You can delete one session or clear everything." action={page && page.total > 0 ? <Button onClick={() => void clear()} disabled={busy}><Trash2 size={16} />Clear history</Button> : undefined} />
    {error && <div className="mb-4 space-y-3"><ErrorMessage message={error} /><Button onClick={() => setRetry((value) => value + 1)}>Retry</Button></div>}
    <Card className="overflow-hidden"><div className="grid gap-3 border-b border-line p-4 sm:grid-cols-[minmax(0,1fr)_minmax(130px,170px)_minmax(130px,170px)] sm:p-5"><Input id="history-search" label="Search this page" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Title or language" /><Select id="history-source" label="Source language" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">Any source</option><option value="auto">Auto detect</option>{apiLanguages.map((language) => <option value={language.code} key={language.code}>{language.name}</option>)}</Select><Select id="history-target" label="Target language" value={targetFilter} onChange={(event) => setTargetFilter(event.target.value)}><option value="">Any target</option>{apiLanguages.map((language) => <option value={language.code} key={language.code}>{language.name}</option>)}</Select><p className="text-xs text-muted sm:col-span-3">Search and filters apply to the current page of up to 20 sessions.</p></div>
      {busy && !page ? <LoadingState label="Loading saved sessions…" /> : !page ? null : page.items.length === 0 ? <EmptyState title="No saved sessions" description="History is off by default. Enable it in Settings, then opt in when translating." action={<Link className="btn-secondary" to="/settings">History settings</Link>} /> : filtered.length === 0 ? <EmptyState title="No matches on this page" description="Try another search or filter, or move to another page." /> : <ul className="divide-y divide-line">{filtered.map((session) => <li key={session.id}><Link to={`/history/${session.id}`} className="flex min-w-0 items-center gap-3 px-4 py-4 transition-colors duration-150 hover:bg-raised sm:px-5"><Clock3 size={17} className="shrink-0 text-muted" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{session.title || 'Untitled session'}</span><span className="mt-1 block truncate text-xs text-muted">{sourceName(session.source_language)} → {languageByCode(session.target_language).name}</span><time dateTime={session.started_at} className="mt-1 block text-xs text-muted sm:hidden">{dateLabel(session.started_at)}</time></span><time dateTime={session.started_at} className="hidden shrink-0 text-xs text-muted sm:block">{dateLabel(session.started_at)}</time><ChevronRight size={16} className="shrink-0 text-muted" /></Link></li>)}</ul>}
      {page && page.total > 20 && <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line px-4 py-3 text-xs text-muted"><span>{offset + 1}–{Math.min(offset + 20, page.total)} of {page.total}</span><Button onClick={() => setOffset(Math.max(0, offset - 20))} disabled={offset === 0 || busy} aria-label="Previous page"><ChevronLeft size={16} />Previous</Button><Button onClick={() => setOffset(offset + 20)} disabled={offset + 20 >= page.total || busy} aria-label="Next page">Next<ChevronRight size={16} /></Button></div>}
    </Card>
  </>
}

export function SessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (!sessionId) return
    let mounted = true
    setBusy(true); setError('')
    void api.session(sessionId, offset).then((value) => { if (mounted) setDetail(value) })
      .catch((cause: unknown) => { if (mounted) setError(cause instanceof Error ? cause.message : 'Could not load this session.') })
      .finally(() => { if (mounted) setBusy(false) })
    return () => { mounted = false }
  }, [sessionId, offset, retry])
  useEffect(() => { let mounted = true; void api.preferences().then((value) => { if (mounted) setPreferences(value) }).catch(() => undefined); return () => { mounted = false } }, [])

  const remove = async () => {
    if (!sessionId || !window.confirm('Delete this session and all of its translations? This cannot be undone.')) return
    setBusy(true); setError('')
    try { await api.deleteSession(sessionId); navigate('/history') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not delete this session.'); setBusy(false) }
  }

  return <><Link to="/history" className="mb-4 inline-flex items-center gap-2 text-sm text-muted hover:text-accent"><ArrowLeft size={16} />All history</Link><PageHeading eyebrow="SESSION DETAILS" title={detail?.session.title || 'Untitled session'} description={detail ? `${dateLabel(detail.session.started_at)} · ${sourceName(detail.session.source_language)} → ${languageByCode(detail.session.target_language).name}` : 'Your saved translation timeline.'} action={detail && <Button onClick={() => void remove()} disabled={busy}><Trash2 size={16} />Delete session</Button>} />
    {error && <div className="mb-4 space-y-3"><ErrorMessage message={error} />{!detail && <Button onClick={() => setRetry((value) => value + 1)}>Retry</Button>}</div>}
    <Card className="overflow-hidden"><div className="flex items-center justify-between border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Translation timeline</h2><span className="text-xs text-muted">{detail?.messages.total ?? 0} messages</span></div>{busy && !detail ? <LoadingState label="Loading translations…" /> : !detail ? null : detail.messages.items.length === 0 ? <EmptyState title="No saved translations" description="This session has no saved messages." /> : <ol className="divide-y divide-line">{detail.messages.items.map((message) => <li key={message.id} className="min-w-0 p-5"><time dateTime={message.created_at} className="text-xs text-muted">{dateLabel(message.created_at)}</time><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-muted">{message.original_text}</p><div className="mt-3 flex min-w-0 items-start justify-between gap-3"><p lang={languageByCode(detail.session.target_language).speech_tag} className="min-w-0 whitespace-pre-wrap break-words text-base leading-7 text-foreground">{message.translated_text}</p><Button variant="ghost" onClick={() => { try { speak(message.translated_text, detail.session.target_language, preferences?.speech_rate || 1) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Playback unavailable.') } }} aria-label="Play translation"><Volume2 size={17} /></Button></div></li>)}</ol>}{detail && detail.messages.total > 50 && <div className="flex justify-end gap-2 border-t border-line p-3"><Button onClick={() => setOffset(Math.max(0, offset - 50))} disabled={offset === 0 || busy}>Previous</Button><Button onClick={() => setOffset(offset + 50)} disabled={offset + 50 >= detail.messages.total || busy}>Next</Button></div>}</Card>
  </>
}
