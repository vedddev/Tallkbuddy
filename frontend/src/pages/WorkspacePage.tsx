import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, AudioLines, Check, Clock3, Headphones, Info, Mic, MicOff, RotateCcw, Send, ShieldCheck, Sparkles, Volume2, Waves } from 'lucide-react'
import { Link } from 'react-router-dom'
import { LanguageSelect } from '../components/LanguageSelect'
import { PageHeading } from '../components/PageHeading'
import { startAudioCapture, type AudioCapture } from '../lib/audio'
import { api } from '../lib/api'
import { speak } from '../lib/speech'
import { TranslationSocket } from '../lib/socket'
import { languages, type Language, type Preferences, type SocketMessage, type SourceLanguage } from '../lib/types'

type Result = Extract<SocketMessage, { type: 'result' }>
type Status = 'idle' | 'connecting' | 'listening' | 'processing' | 'stopping' | 'disconnected'

function statusLabel(status: Status) {
  return { idle: 'Ready when you are', connecting: 'Connecting…', listening: 'Listening now', processing: 'Translating…', stopping: 'Finishing…', disconnected: 'Disconnected' }[status]
}

export function WorkspacePage() {
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [source, setSource] = useState<SourceLanguage>('auto')
  const [target, setTarget] = useState<Language>('fr')
  const [saveHistory, setSaveHistory] = useState(false)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  const [results, setResults] = useState<Result[]>([])
  const [typedText, setTypedText] = useState('')
  const [typingBusy, setTypingBusy] = useState(false)
  const [droppedAudio, setDroppedAudio] = useState(false)
  const captureRef = useRef<AudioCapture | null>(null)
  const socketRef = useRef<TranslationSocket | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    api.preferences().then((value) => {
      if (!mountedRef.current) return
      setPreferences(value)
      setSource(value.source_language)
      setTarget(value.target_language)
    }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Could not load preferences.'))
    return () => {
      mountedRef.current = false
      void captureRef.current?.abort().catch(() => undefined)
      socketRef.current?.close()
      if (sessionIdRef.current) void api.endSession(sessionIdRef.current).catch(() => undefined)
      window.speechSynthesis?.cancel()
    }
  }, [])

  const endSavedSession = async () => {
    const id = sessionIdRef.current
    sessionIdRef.current = null
    if (id) await api.endSession(id)
  }

  const handleMessage = (message: SocketMessage) => {
    if (message.type === 'processing') setStatus('processing')
    if (message.type === 'result') { setResults((items) => [message, ...items].slice(0, 30)); setStatus('listening'); setError('') }
    if (message.type === 'error') { setError(message.message); setStatus(message.recoverable ? 'listening' : 'disconnected') }
  }

  const start = async () => {
    if (status === 'connecting' || status === 'listening' || status === 'processing') return
    if (saveHistory && !preferences?.save_history_enabled) { setError('Enable history saving in Settings first.'); return }
    setError(''); setDroppedAudio(false); setStatus('connecting')
    let connection: TranslationSocket | null = null
    try {
      if (saveHistory) {
        const session = await api.createSession(source, target)
        sessionIdRef.current = session.id
      }
      connection = new TranslationSocket({
        onMessage: handleMessage,
        onDrop: () => setDroppedAudio(true),
        onClose: (reason) => {
          if (!mountedRef.current) return
          setStatus('disconnected'); setError(reason)
          void captureRef.current?.abort().catch(() => undefined)
          captureRef.current = null
          void endSavedSession().catch(() => undefined)
        },
      })
      socketRef.current = connection
      await connection.connect({ source_language: source, target_language: target, save_history: saveHistory, session_id: sessionIdRef.current || undefined })
      captureRef.current = await startAudioCapture((wav) => connection?.sendAudio(wav))
      if (!connection.isOpen()) throw new Error('Connection closed while waiting for the microphone. Reconnect to try again.')
      setStatus('listening')
    } catch (cause) {
      await captureRef.current?.abort().catch(() => undefined)
      captureRef.current = null
      connection?.close(); socketRef.current = null
      try { await endSavedSession() } catch { /* session can be ended from History later */ }
      setStatus('idle')
      setError(cause instanceof Error ? cause.message : 'Could not start translation.')
    }
  }

  const stop = async () => {
    if (status === 'idle' || status === 'stopping') return
    setStatus('stopping'); setError('')
    try {
      await captureRef.current?.stop()
      captureRef.current = null
      await socketRef.current?.stop()
      socketRef.current = null
      await endSavedSession()
      setStatus('idle')
    } catch (cause) {
      socketRef.current?.close(); socketRef.current = null
      setStatus('idle')
      setError(cause instanceof Error ? cause.message : 'Could not end the session cleanly.')
    }
  }

  const translateTyped = async (event: FormEvent) => {
    event.preventDefault()
    const text = typedText.trim()
    if (!text) return
    if (saveHistory && !preferences?.save_history_enabled) { setError('Enable history saving in Settings first.'); return }
    setTypingBusy(true); setError('')
    let sessionId: string | undefined
    try {
      if (saveHistory) sessionId = (await api.createSession(source, target)).id
      const translated = await api.translateText(text, target, sessionId)
      const typedResult: Result = { type: 'result', chunk_id: Date.now(), original: translated.original_text, translated: translated.translated_text, detected_language: null, target_language: target, processing_time_ms: 0, saved: translated.saved, message_id: translated.message_id }
      setResults((items) => [typedResult, ...items].slice(0, 30))
      setTypedText('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Translation failed.') }
    finally {
      if (sessionId) await api.endSession(sessionId).catch(() => undefined)
      setTypingBusy(false)
    }
  }

  const active = status === 'listening' || status === 'processing' || status === 'connecting' || status === 'stopping'
  const latest = results[0]
  const targetName = languages.find((item) => item.code === target)?.name || target

  return <>
    <PageHeading eyebrow="YOUR TRANSLATION STUDIO" title="Let’s get talking." description="A space for the conversations that go beyond words. Choose your languages, press the microphone, and speak naturally." action={<span className={`inline-flex items-center gap-2 self-start rounded-full px-4 py-2 text-xs font-semibold ${active ? 'bg-[#e1f5e8] text-mint dark:bg-mint/20 dark:text-lime' : 'bg-white text-slate-500 dark:bg-white/5 dark:text-slate-400'}`}><span className={`h-2 w-2 rounded-full ${active ? 'animate-pulse bg-mint' : 'bg-slate-300'}`} />{statusLabel(status)}</span>} />
    {error && <div role="alert" className="mb-5 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-200"><Info size={18} className="mt-0.5 shrink-0" />{error}</div>}
    <div id="translate" className="grid scroll-mt-24 gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,.9fr)]">
      <div className="space-y-6">
        <section className="panel overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-5 dark:border-white/10"><div className="flex items-center gap-3"><div className="grid h-9 w-9 place-items-center rounded-xl bg-[#e5f5ec] text-mint dark:bg-mint/20 dark:text-lime"><AudioLines size={20} /></div><div><h2 className="text-sm font-semibold">Live translation</h2><p className="text-xs text-slate-400">Speak, listen, connect</p></div></div><span className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">PCM WAV · 16 kHz</span></div>
          <div className="p-6 md:p-8"><div className="grid gap-4 sm:grid-cols-[1fr_42px_1fr] sm:items-end"><LanguageSelect id="source-language" label="I’m speaking" value={source} onChange={setSource} allowAuto disabled={active} /><div className="mb-3 hidden place-items-center text-slate-400 sm:grid"><ArrowRight size={19} /></div><LanguageSelect id="target-language" label="Translate to" value={target} onChange={(value) => setTarget(value as Language)} disabled={active} /></div><div className="mt-8 rounded-[24px] bg-[#f5f8f4] p-6 dark:bg-[#203033] md:p-8"><div className="flex items-center justify-between"><span className="text-xs font-semibold uppercase tracking-[.14em] text-slate-400">Microphone</span><span className="flex items-center gap-2 text-xs text-slate-400"><span className={`h-2 w-2 rounded-full ${active ? 'animate-pulse bg-mint' : 'bg-slate-300'}`} />{active ? 'Active session' : 'Not recording'}</span></div><div className="flex flex-col items-center pb-3 pt-9"><button type="button" onClick={active ? () => void stop() : () => void start()} disabled={status === 'connecting' || status === 'stopping'} className={`grid h-24 w-24 place-items-center rounded-full text-white shadow-[0_12px_38px_rgba(15,140,117,.25)] transition hover:scale-105 disabled:cursor-wait disabled:opacity-65 ${active ? 'bg-[#db5e55]' : 'bg-mint'}`} aria-label={active ? 'Stop translation' : 'Start translation'}>{active ? <MicOff size={34} /> : <Mic size={34} />}</button><p className="mt-5 text-lg font-semibold">{active ? 'Tap to stop translating' : 'Tap to start speaking'}</p><p className="mt-1 text-center text-sm text-slate-500 dark:text-slate-400">{active ? 'Your conversation is being translated in short moments.' : 'Allow microphone access when your browser asks.'}</p>{active && <div className="mt-6 flex h-8 items-center gap-1.5" aria-hidden="true">{[14, 25, 18, 30, 19, 34, 14, 26, 18, 31, 16, 23, 13].map((height, index) => <span key={index} className="animate-wave w-1 rounded-full bg-mint" style={{ height, animationDelay: `${index * 80}ms` }} />)}</div>}</div></div>
          <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-xl border border-slate-100 px-4 py-3 dark:border-white/10"><input type="checkbox" checked={saveHistory} disabled={active || !preferences?.save_history_enabled} onChange={(event) => setSaveHistory(event.target.checked)} className="mt-0.5 h-4 w-4 accent-mint" /><span><span className="block text-sm font-semibold">Save this conversation</span><span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">Off by default. {preferences?.save_history_enabled ? 'You can delete it any time.' : <>Enable saving in <Link to="/settings" className="text-mint underline dark:text-lime">Settings</Link> first.</>}</span></span></label>{droppedAudio && <p className="mt-3 text-xs text-amber-700 dark:text-amber-300">Some audio was skipped while translation caught up. Try speaking in shorter phrases.</p>}</div></section>
        <section className="panel p-6 md:p-8"><div className="flex items-center gap-3"><div className="grid h-9 w-9 place-items-center rounded-xl bg-[#f1edff] text-[#7f67c7] dark:bg-white/10"><Send size={18} /></div><div><h2 className="text-sm font-semibold">Or type a message</h2><p className="text-xs text-slate-400">A quick translation without the microphone</p></div></div><form onSubmit={translateTyped} className="mt-5"><label className="sr-only" htmlFor="typed-text">Text to translate</label><textarea id="typed-text" value={typedText} onChange={(event) => setTypedText(event.target.value)} maxLength={5000} rows={3} placeholder="Type a sentence to translate…" className="field w-full resize-y" /><div className="mt-3 flex items-center justify-between"><span className="text-xs text-slate-400">{typedText.length} / 5000 characters</span><button className="btn-primary" disabled={!typedText.trim() || typingBusy}>{typingBusy ? 'Translating…' : 'Translate text'}<ArrowRight size={16} /></button></div></form></section>
      </div>
      <div className="space-y-6"><section className="panel min-h-[416px] p-6 md:p-7"><div className="flex items-center justify-between"><div><p className="eyebrow">THE CONVERSATION</p><h2 className="mt-1 text-xl font-semibold">Latest translation</h2></div><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#e6f6ec] text-mint dark:bg-mint/20 dark:text-lime"><Sparkles size={19} /></div></div>{latest ? <div className="mt-7 space-y-4"><div className="rounded-2xl border border-slate-100 p-5 dark:border-white/10"><p className="text-[11px] font-semibold uppercase tracking-[.14em] text-slate-400">Original</p><p className="mt-3 text-base leading-7">{latest.original}</p></div><div className="rounded-2xl bg-[#e7f5eb] p-5 dark:bg-mint/15"><div className="flex items-center justify-between"><p className="text-[11px] font-semibold uppercase tracking-[.14em] text-mint dark:text-lime">In {targetName}</p><button onClick={() => { try { speak(latest.translated, latest.target_language, preferences?.speech_rate || 1) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Playback unavailable.') } }} className="icon-btn text-mint dark:text-lime" aria-label="Play translation"><Volume2 size={19} /></button></div><p className="mt-3 text-lg font-medium leading-7">{latest.translated}</p></div><div className="flex items-center justify-between text-xs text-slate-400"><span className="flex items-center gap-1"><Clock3 size={13} /> {latest.processing_time_ms ? `${(latest.processing_time_ms / 1000).toFixed(1)}s processing` : 'Text translation'}</span><span className="flex items-center gap-1">{latest.saved ? <><Check size={13} /> Saved</> : <><ShieldCheck size={13} /> Not saved</>}</span></div></div> : <div className="flex min-h-[285px] flex-col items-center justify-center text-center"><div className="grid h-16 w-16 place-items-center rounded-[22px] bg-[#eef5ed] text-mint dark:bg-white/5"><Waves size={29} /></div><h3 className="mt-5 font-semibold">Your words will appear here</h3><p className="mt-2 max-w-[240px] text-sm leading-6 text-slate-400">Start speaking or type a message to see your translation.</p></div>}</section><div className="rounded-[22px] bg-[#173f38] p-6 text-white"><Headphones className="text-lime" size={23} /><h3 className="mt-4 text-base font-semibold">Talk naturally.</h3><p className="mt-2 text-sm leading-6 text-white/65">Short, clear phrases work best. Your microphone audio is never stored by TalkBuddy.</p></div>{status === 'disconnected' && <button onClick={() => void start()} className="btn-secondary w-full justify-center"><RotateCcw size={17} /> Reconnect</button>}</div>
    </div>
    {results.length > 1 && <section className="mt-7"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">Recent moments</h2><span className="text-xs text-slate-400">This page keeps up to 30 results in memory</span></div><div className="grid gap-3 md:grid-cols-2">{results.slice(1, 7).map((item) => <div key={`${item.chunk_id}-${item.message_id || item.original}`} className="panel p-5"><p className="line-clamp-2 text-sm text-slate-500 dark:text-slate-400">{item.original}</p><p className="mt-3 line-clamp-2 font-medium">{item.translated}</p></div>)}</div></section>}
  </>
}
