import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowLeftRight, Check, Copy, Languages, Volume2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { LanguageSelect } from '../components/LanguageSelect'
import { PageHeading } from '../components/PageHeading'
import { Button, Card, EmptyState, ErrorMessage, LoadingState } from '../components/ui/Primitives'
import { api } from '../lib/api'
import { languageByCode } from '../lib/languageRegistry'
import { speak } from '../lib/speech'
import type { Language, Preferences, SourceLanguage } from '../lib/types'

type TranslationResult = Awaited<ReturnType<typeof api.translateText>>

export function TranslatePage() {
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [source, setSource] = useState<SourceLanguage>('auto')
  const [target, setTarget] = useState<Language>('hi')
  const [input, setInput] = useState('')
  const [result, setResult] = useState<TranslationResult | null>(null)
  const [saveHistory, setSaveHistory] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [copied, setCopied] = useState(false)
  const inFlightRef = useRef(false)

  useEffect(() => {
    let mounted = true
    void api.preferences().then((value) => {
      if (!mounted) return
      setPreferences(value); setSource(value.source_language); setTarget(value.target_language)
    }).catch(() => { if (mounted) setNotice('Saved preferences are unavailable. You can still translate without saving history.') })
    return () => { mounted = false }
  }, [])

  const translate = async (event: FormEvent) => {
    event.preventDefault()
    const text = input.trim()
    if (!text || inFlightRef.current) return
    if (saveHistory && !preferences?.save_history_enabled) { setError('Enable history saving in Settings before opting in.'); return }
    inFlightRef.current = true
    setLoading(true); setError(''); setNotice(''); setCopied(false)
    setResult(null)
    let sessionId: string | undefined
    try {
      if (saveHistory) sessionId = (await api.createSession(source, target)).id
      setResult(await api.translateText(text, target, sessionId))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Translation failed. Try again.')
    } finally {
      if (sessionId) await api.endSession(sessionId).catch(() => setNotice('The saved session could not be closed. You can manage it in History.'))
      inFlightRef.current = false
      setLoading(false)
    }
  }

  const swap = () => {
    if (source === 'auto' || loading) return
    const previousTarget = target
    setTarget(source)
    setSource(previousTarget)
    if (result) setInput(result.translated_text)
    setResult(null); setError(''); setNotice(''); setCopied(false)
  }

  const copy = async () => {
    if (!result) return
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable in this browser.')
      await navigator.clipboard.writeText(result.translated_text)
      setCopied(true); setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not copy the translation.') }
  }

  const play = () => {
    if (!result) return
    try { speak(result.translated_text, result.target_language, preferences?.speech_rate || 1); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Speech playback is unavailable.') }
  }

  return <>
    <PageHeading eyebrow="TRANSLATE" title="Text Translation" description="Write a complete phrase and translate it into one of TalkBuddy’s supported languages." />
    {error && <div className="mb-4"><ErrorMessage message={error} /></div>}
    {notice && <p role="status" className="mb-4 rounded-lg border border-line bg-raised px-4 py-3 text-sm text-muted">{notice}</p>}
    <Card className="mb-4 p-4 sm:p-5"><div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-end"><LanguageSelect id="translate-source" label="Source language" value={source} onChange={setSource} allowAuto disabled={loading} /><Button type="button" onClick={swap} disabled={source === 'auto' || loading} aria-label="Swap languages" title={source === 'auto' ? 'Select a source language to swap' : 'Swap source and target'} className="h-[42px]"><ArrowLeftRight size={16} /></Button><LanguageSelect id="translate-target" label="Target language" value={target} onChange={(value) => setTarget(value as Language)} disabled={loading} /></div><p className="mt-3 text-xs leading-5 text-muted">The text API detects the actual source language automatically. The source selector labels your input and enables swapping; it is not sent as a provider hint.</p></Card>
    <form onSubmit={(event) => void translate(event)}><div className="grid min-w-0 gap-4 lg:grid-cols-2"><Card className="flex min-h-[360px] min-w-0 flex-col p-4 sm:p-5"><div className="flex items-center justify-between"><h2 className="flex items-center gap-2 text-sm font-semibold"><Languages size={17} className="text-accent" />Original text</h2><span className="text-xs text-muted">{input.length} / 5000</span></div><label htmlFor="translation-input" className="sr-only">Text to translate</label><textarea id="translation-input" className="field mt-4 min-h-48 w-full flex-1 resize-y whitespace-pre-wrap text-base leading-7" maxLength={5000} placeholder="Write a phrase to translate…" value={input} onChange={(event) => setInput(event.target.value)} disabled={loading} /><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={saveHistory} disabled={loading || !preferences?.save_history_enabled} onChange={(event) => setSaveHistory(event.target.checked)} className="accent-accent" />Save this translation</label><Button type="submit" variant="primary" busy={loading} disabled={!input.trim()}>Translate text</Button></div><p className="mt-2 text-xs text-muted">{preferences?.save_history_enabled ? 'Saving requires this opt-in for each translation.' : <>History is off. Enable it in <Link to="/settings" className="text-accent underline">Settings</Link> to save text.</>}</p></Card>
      <Card className="flex min-h-[360px] min-w-0 flex-col p-4 sm:p-5"><div className="flex items-center justify-between gap-3"><h2 className="text-sm font-semibold">Translated text</h2><span className="text-xs text-muted">{result ? languageByCode(result.target_language).name : languageByCode(target).name}</span></div><div aria-live="polite" className="mt-4 min-w-0 flex-1">{loading ? <LoadingState label="Translating…" /> : result ? <p lang={languageByCode(result.target_language).speech_tag} className="whitespace-pre-wrap break-words text-base leading-8 text-foreground">{result.translated_text}</p> : <EmptyState title="Ready to translate" description="Your translated phrase will appear here." />}</div><div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4"><span className="text-xs text-muted">{result ? result.saved ? 'Saved to history' : 'History off for this result' : 'No result yet'}</span><div className="flex gap-2"><Button type="button" onClick={() => void copy()} disabled={!result || loading} aria-label="Copy translation">{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? 'Copied' : 'Copy'}</Button><Button type="button" onClick={play} disabled={!result || loading} aria-label="Speak translation"><Volume2 size={16} />Speak</Button></div></div></Card></div></form>
  </>
}
