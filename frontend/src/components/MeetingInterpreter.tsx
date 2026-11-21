import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AudioLines, Captions, Headphones, Mic2, Pause, Play, Radio, Square, Volume2, VolumeX } from 'lucide-react'
import { Link } from 'react-router-dom'
import { LanguageSelect } from './LanguageSelect'
import { LatencyDiagnostics } from './LatencyDiagnostics'
import { Button, Card, ErrorMessage, StatusIndicator } from './ui/Primitives'
import { api } from '../lib/api'
import { languageByCode } from '../lib/languageRegistry'
import { detectedLanguageLabel, detectedLanguageTag } from '../lib/detectedLanguage'
import { appendTiming, durationMs, timingRecord, type CaptureTiming, type PhraseTimingRecord } from '../lib/latency'
import { startMeetingCapture, startMicrophoneCapture, type MeetingCapture } from '../lib/meetingAudio'
import { AutoSpeechQueue, type SpeechProvider } from '../lib/autoSpeechQueue'
import type { PlaybackStatus } from '../lib/speechQueue'
import { TranslationSocket } from '../lib/socket'
import { voiceForLanguage } from '../lib/voices'
import type { Language, Preferences, SocketMessage, SourceLanguage } from '../lib/types'

type Result = Extract<SocketMessage, { type: 'result' }>
type TimedResult = Result & { receivedAt: number; displayId: number; translationFailed?: boolean }
type Status = 'idle' | 'permission' | 'shared' | 'connecting' | 'listening' | 'paused' | 'reconnecting' | 'stopping' | 'disconnected' | 'error'

interface Props {
  preferences: Preferences | null
  microphoneActive: boolean
  onActiveChange: (active: boolean) => void
  mode?: 'meeting' | 'microphone'
}

const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))
export const reconnectDelayMs = (attempt: number, random = Math.random()): number =>
  Math.min(4_000, Math.round(1_000 * 2 ** Math.max(0, Math.min(2, attempt)) * (0.8 + 0.4 * Math.max(0, Math.min(1, random)))))
const statusLabels: Record<Status, string> = {
  idle: 'Idle', permission: 'Requesting tab permission', shared: 'Tab shared', connecting: 'Connecting',
  listening: 'Listening', paused: 'Paused', reconnecting: 'Reconnecting', stopping: 'Stopping',
  disconnected: 'Disconnected', error: 'Error',
}

function phraseTime(value: number) {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(value)
}

function socketErrorMessage(message: Extract<SocketMessage, { type: 'error' }>): string {
  if (message.code === 'provider_timeout' || message.code === 'processing_timeout') return 'Translation timed out. Try a shorter phrase and retry.'
  if (message.code === 'provider_unavailable' || message.code === 'provider_error') return 'AI translation is temporarily unavailable. Wait a moment and try again.'
  if (message.code === 'session_invalid' || message.code === 'session_check_failed') return 'Your session is no longer valid. Sign in again.'
  if (message.code === 'no_speech') return 'No clear speech was detected. Check that the shared tab has audio.'
  if (message.code === 'invalid_audio') return 'The audio chunk was invalid. Stop and share the meeting tab again.'
  if (message.code === 'unsupported_language') return 'This language is unavailable. Stop and choose another language.'
  if (message.code === 'chunk_limit') return 'This connection reached its phrase limit. Stop and start a new session.'
  if (message.code === 'audio_too_large') return 'A phrase was too large. Try speaking in shorter phrases.'
  return message.message
}

function PhrasePanel({ title, icon, results, field, empty, pending, language }: {
  title: string; icon: React.ReactNode; results: TimedResult[]; field: 'original' | 'translated';
  empty: string; pending: boolean; language?: string
}) {
  const scrollRef = useRef<HTMLOListElement>(null)
  const followRef = useRef(true)
  const latest = results.at(-1)?.displayId
  useLayoutEffect(() => {
    if (followRef.current && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [latest, results.length])
  return <Card className="flex min-h-[320px] min-w-0 flex-col overflow-hidden lg:min-h-[440px]">
    <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5"><h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">{icon}{title}</h3>{language && <span className="truncate text-xs text-muted">{language}</span>}</div>
    <ol ref={scrollRef} aria-label={title} onScroll={(event) => {
      const node = event.currentTarget
      followRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 56
    }} className="max-h-[460px] min-h-[260px] flex-1 space-y-3 overflow-y-auto p-4 sm:p-5">
      {results.length ? results.map((item) => <li key={item.displayId} className="min-w-0 rounded-lg border border-line bg-raised/50 p-3.5">
        <div className="mb-2 flex items-center justify-between gap-2 text-[11px] text-muted"><span>Completed phrase {item.chunk_id}{field === 'original' ? ` · ${detectedLanguageLabel(item.detected_language, item.language_detection_source)}` : ''}</span><time dateTime={new Date(item.receivedAt).toISOString()} title="Received by TalkBuddy">Received {phraseTime(item.receivedAt)}</time></div>
        <p lang={field === 'translated' ? languageByCode(item.target_language).speech_tag : detectedLanguageTag(item.detected_language)} className="whitespace-pre-wrap break-words text-sm leading-7 text-foreground sm:text-base">{field === 'translated' && item.translationFailed ? 'Translation unavailable for this phrase.' : item[field]}</p>
      </li>) : <li className="flex min-h-[220px] flex-col items-center justify-center gap-3 text-center"><span className="grid h-11 w-11 place-items-center rounded-lg bg-raised text-muted">{icon}</span><p className="max-w-xs text-sm leading-6 text-muted">{empty}</p></li>}
      {pending && <li role="status" className="text-xs text-muted">Processing a complete phrase…</li>}
    </ol>
  </Card>
}

export function MeetingInterpreter({ preferences, microphoneActive, onActiveChange, mode = 'meeting' }: Props) {
  const [source, setSource] = useState<SourceLanguage>('auto')
  const [target, setTarget] = useState<Language>('hi')
  const [saveHistory, setSaveHistory] = useState(false)
  const [muteOriginal, setMuteOriginal] = useState(false)
  const [muteTranslated, setMuteTranslated] = useState(false)
  const [speechProvider, setSpeechProvider] = useState<SpeechProvider>('captions')
  const [deviceId, setDeviceId] = useState('')
  const [microphones, setMicrophones] = useState<MediaDeviceInfo[]>([])
  const [status, setStatus] = useState<Status>('idle')
  const [processing, setProcessing] = useState(false)
  const [playback, setPlayback] = useState<PlaybackStatus>('idle')
  const [queuedSpeech, setQueuedSpeech] = useState(0)
  const [activity, setActivity] = useState(0)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [results, setResults] = useState<TimedResult[]>([])
  const [timings, setTimings] = useState<PhraseTimingRecord[]>([])
  const [phraseCount, setPhraseCount] = useState(0)
  const [capturedPhrases, setCapturedPhrases] = useState(0)
  const [processingErrors, setProcessingErrors] = useState(0)
  const [droppedPhrases, setDroppedPhrases] = useState(0)
  const [droppedSamples, setDroppedSamples] = useState(0)
  const [bufferOverflows, setBufferOverflows] = useState(0)
  const [websocketDisconnects, setWebsocketDisconnects] = useState(0)
  const [playbackFailures, setPlaybackFailures] = useState(0)
  const [queueDepth, setQueueDepth] = useState(0)
  const captureRef = useRef<MeetingCapture | null>(null)
  const socketRef = useRef<TranslationSocket | null>(null)
  const speechRef = useRef<AutoSpeechQueue | null>(null)
  const audioIdsRef = useRef(new Map<number, number>())
  const sessionIdRef = useRef<string | null>(null)
  const generationRef = useRef(0)
  const startingRef = useRef(false)
  const startedRef = useRef(false)
  const terminalErrorRef = useRef(false)
  const reconnectingRef = useRef(false)
  const pausedRef = useRef(false)
  const mountedRef = useRef(true)
  const seenResultsRef = useRef(new Set<number>())
  const playbackSequenceRef = useRef(0)
  const displaySequenceRef = useRef(0)

  useEffect(() => {
    if (status !== 'idle' || !preferences) return
    setSource(preferences.source_language)
    setTarget(preferences.target_language)
  }, [preferences, status])

  useEffect(() => {
    const synth = window.speechSynthesis
    if (!synth?.getVoices) return
    const update = () => setVoices(synth.getVoices())
    update()
    synth.addEventListener?.('voiceschanged', update)
    return () => synth.removeEventListener?.('voiceschanged', update)
  }, [])

  useEffect(() => {
    if (mode !== 'microphone' || !navigator.mediaDevices?.enumerateDevices) return
    let live = true
    const refresh = () => { void navigator.mediaDevices.enumerateDevices().then((devices) => {
      if (live) setMicrophones(devices.filter((device) => device.kind === 'audioinput'))
    }).catch(() => { if (live) setNotice('Microphone list is unavailable. You can still try the browser default input.') }) }
    refresh()
    navigator.mediaDevices.addEventListener?.('devicechange', refresh)
    return () => { live = false; navigator.mediaDevices.removeEventListener?.('devicechange', refresh) }
  }, [mode])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      generationRef.current += 1
      socketRef.current?.close()
      void captureRef.current?.stop()
      speechRef.current?.stop()
      if (sessionIdRef.current) void api.endSession(sessionIdRef.current).catch(() => undefined)
      onActiveChange(false)
    }
  }, [onActiveChange])

  const stop = async (graceful = true, finalStatus: Status = 'idle') => {
    generationRef.current += 1
    startingRef.current = false
    startedRef.current = false
    reconnectingRef.current = false
    pausedRef.current = false
    setStatus('stopping')
    setActivity(0)
    setProcessing(false)
    const capture = captureRef.current
    captureRef.current = null
    await capture?.stop().catch(() => undefined)
    speechRef.current?.stop()
    speechRef.current = null
    setSpeechProvider('captions')
    audioIdsRef.current.clear()
    setPlayback('idle')
    setQueuedSpeech(0)
    const socket = socketRef.current
    socketRef.current = null
    if (graceful) await socket?.stop().catch(() => socket.close())
    else socket?.close()
    seenResultsRef.current.clear()
    const sessionId = sessionIdRef.current
    sessionIdRef.current = null
    if (sessionId) await api.endSession(sessionId).catch(() => setNotice('Could not close the saved session. You can manage it in History.'))
    onActiveChange(false)
    if (mountedRef.current) setStatus(finalStatus)
  }

  const connect = async (generation: number) => {
    const socket = new TranslationSocket({
      onMessage: (message, timing) => {
        if (generation !== generationRef.current || !mountedRef.current || !startedRef.current) return
        if (message.type === 'processing') setProcessing(true)
        if (message.type === 'result') {
          setProcessing(false)
          if (seenResultsRef.current.has(message.chunk_id)) return
          seenResultsRef.current.add(message.chunk_id)
          setResults((items) => [...items, { ...message, receivedAt: Date.now(), displayId: ++displaySequenceRef.current }].slice(-30))
          setError('')
          const playbackSequence = ++playbackSequenceRef.current
          audioIdsRef.current.set(message.chunk_id, playbackSequence)
          if (audioIdsRef.current.size > 16) audioIdsRef.current.delete(audioIdsRef.current.keys().next().value!)
          setTimings((items) => appendTiming(items, timingRecord(playbackSequence, message, timing)))
          if (!muteTranslated && !speechRef.current?.addResult(playbackSequence, message.translated, message.target_language, preferences?.speech_rate || 1)) { setPlaybackFailures((count) => count + 1); setNotice('Speech playback is behind; captions remain available.') }
        }
        if (message.type === 'speech_audio') {
          const id = audioIdsRef.current.get(message.chunk_id)
          audioIdsRef.current.delete(message.chunk_id)
          if (id !== undefined) setTimings((items) => items.map((item) => item.id === id ? { ...item, ttsMs: message.preparation_time_ms ?? null } : item))
          if (id !== undefined && !muteTranslated) speechRef.current?.addAudio(id, message.audio_base64)
        }
        if (message.type === 'speech_error') { const id = audioIdsRef.current.get(message.chunk_id); audioIdsRef.current.delete(message.chunk_id); if (id !== undefined) speechRef.current?.speechError(id); setPlaybackFailures((count) => count + 1) }
        if (message.type === 'error') {
          if (message.code === 'speech_unavailable') { speechRef.current?.disableAzure(); return }
          setProcessing(false)
          setProcessingErrors((count) => count + 1)
          setError(socketErrorMessage(message))
          if (message.original && message.chunk_id && !seenResultsRef.current.has(message.chunk_id)) {
            seenResultsRef.current.add(message.chunk_id)
            const failedResult: TimedResult = {
              type: 'result', chunk_id: message.chunk_id, original: message.original, translated: '',
              detected_language: message.detected_language ?? null,
              language_detection_source: message.language_detection_source,
              target_language: target, processing_time_ms: 0,
              receivedAt: Date.now(), displayId: ++displaySequenceRef.current, translationFailed: true,
            }
            setResults((items) => [...items, failedResult].slice(-30))
          }
          if (!message.recoverable) { terminalErrorRef.current = true; captureRef.current?.pause(); setActivity(0) }
        }
      },
      onDrop: () => { setDroppedPhrases((count) => count + 1); setNotice('Translation is behind; one phrase was skipped to keep memory bounded.') },
      onQueueChange: (depth) => { if (mountedRef.current) setQueueDepth(depth) },
      onClose: (reason) => {
        if (generation !== generationRef.current || !startedRef.current || reconnectingRef.current) return
        setWebsocketDisconnects((count) => count + 1)
        captureRef.current?.pause()
        speechRef.current?.pause()
        setActivity(0)
        setProcessing(false)
        if (terminalErrorRef.current) void stop(false, 'error')
        else if (reason.includes('session expired')) { setError('Your session expired. Sign in again.'); void stop(false, 'error') }
        else void reconnect(generation)
      },
    })
    socketRef.current = socket
    await socket.connect({ source_language: source, target_language: target, save_history: saveHistory, session_id: sessionIdRef.current || undefined, synthesize_speech: true, allow_speech_fallback: true })
    if (socket.usedSpeechFallback()) speechRef.current?.disableAzure()
  }

  const reconnect = async (generation: number) => {
    if (reconnectingRef.current) return
    reconnectingRef.current = true
    setStatus('reconnecting')
    for (let attempt = 0; attempt < 3; attempt++) {
      const delay = reconnectDelayMs(attempt)
      await wait(delay)
      if (generation !== generationRef.current) return
      try {
        await connect(generation)
        if (generation !== generationRef.current) return
        seenResultsRef.current.clear()
        audioIdsRef.current.clear()
        speechRef.current?.mute()
        if (!pausedRef.current) { captureRef.current?.resume(); speechRef.current?.resume() }
        reconnectingRef.current = false
        setError('')
        setStatus(pausedRef.current ? 'paused' : 'listening')
        return
      } catch (cause) {
        socketRef.current?.close()
        const message = cause instanceof Error ? cause.message : ''
        if (/session expired|not authorized|sign in again|Azure speech is not configured/i.test(message)) {
          setError(message)
          reconnectingRef.current = false
          await stop(false, 'error')
          return
        }
      }
    }
    reconnectingRef.current = false
    setError('Connection lost. Check the backend and restart interpretation.')
    await stop(false, 'disconnected')
  }

  const prepareCapture = async (generation: number): Promise<MeetingCapture | null> => {
    setStatus('permission'); setError(''); setNotice('')
    const onChunk = (wav: ArrayBuffer, captureTiming: CaptureTiming) => {
      if (generation !== generationRef.current || !mountedRef.current) return
      setCapturedPhrases((count) => count + 1)
      const socket = socketRef.current
      if (!socket?.isOpen()) { setDroppedPhrases((count) => count + 1); setNotice('A phrase was skipped while reconnecting.') }
      else if (socket.sendAudio(wav, captureTiming)) setPhraseCount((count) => count + 1)
    }
    const onEnded = () => { if (generation === generationRef.current) { setNotice(mode === 'meeting' ? 'Tab sharing ended.' : 'Microphone disconnected.'); void stop(false) } }
    const onDrop = () => { if (generation === generationRef.current && mountedRef.current) { setDroppedPhrases((count) => count + 1); setNotice('A long uninterrupted phrase had no safe boundary and was skipped.') } }
    const onActivity = (level: number) => { if (generation === generationRef.current && mountedRef.current) setActivity(level) }
    const onDroppedSamples = (count: number, discardedPhrase: boolean, overflowEvents: number) => {
      if (generation !== generationRef.current || !mountedRef.current) return
      setDroppedSamples((value) => value + count)
      setBufferOverflows((value) => value + overflowEvents)
      if (discardedPhrase) setDroppedPhrases((value) => value + 1)
      setNotice(discardedPhrase
        ? 'Audio capture fell behind. A partial phrase was discarded; try closing busy tabs.'
        : 'Audio capture fell behind during silence; try closing busy tabs.')
    }
    const capture = mode === 'meeting' ? await startMeetingCapture(
      onChunk, onEnded, onDrop, muteOriginal, onActivity, onDroppedSamples,
    ) : await startMicrophoneCapture(onChunk, onEnded, onDrop, deviceId || undefined, onActivity, onDroppedSamples)
    if (generation !== generationRef.current || !mountedRef.current) { await capture.stop(); return null }
    captureRef.current = capture
    onActiveChange(true)
    if (mode === 'meeting' && muteOriginal && !capture.originalMuteSupported) {
      setMuteOriginal(false)
      setNotice('This browser cannot mute the source tab from TalkBuddy. Use the tab mute control if needed.')
    }
    setStatus(mode === 'meeting' ? 'shared' : 'connecting')
    return capture
  }

  const shareTab = async () => {
    if (startingRef.current || !['idle', 'error', 'disconnected'].includes(status)) return
    if (microphoneActive) { setError('Stop microphone translation before sharing a meeting tab.'); return }
    startingRef.current = true
    const generation = ++generationRef.current
    try { await prepareCapture(generation) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not share this tab. Check browser permissions.'); setStatus('error') }
    finally { startingRef.current = false }
  }

  const start = async () => {
    if (startingRef.current || !['idle', 'error', 'disconnected', 'shared'].includes(status)) return
    if (mode === 'meeting' && microphoneActive) { setError('Stop microphone translation before listening to a meeting.'); return }
    if (saveHistory && !preferences?.save_history_enabled) { setError('Enable history saving in Settings first.'); return }
    startingRef.current = true
    const generation = status === 'shared' ? generationRef.current : ++generationRef.current
    pausedRef.current = false
    terminalErrorRef.current = false
    setError(''); setNotice(''); setResults([]); setTimings([]); setProcessing(false); setPlayback('idle')
    setPhraseCount(0); setCapturedPhrases(0); setProcessingErrors(0); setDroppedPhrases(0); setDroppedSamples(0); setBufferOverflows(0); setWebsocketDisconnects(0); setPlaybackFailures(0); setQueueDepth(0)
    seenResultsRef.current.clear()
    playbackSequenceRef.current = 0
    displaySequenceRef.current = 0
    try {
      // Capture is requested directly from the click when the tab has not already been shared.
      const capture = captureRef.current || await prepareCapture(generation)
      if (!capture || generation !== generationRef.current) return
      setStatus('connecting')
      if (saveHistory) {
        const session = await api.createSession(source, target)
        if (generation !== generationRef.current) { await api.endSession(session.id).catch(() => undefined); return }
        sessionIdRef.current = session.id
      }
      speechRef.current = new AutoSpeechQueue(
        window.speechSynthesis || null,
        (provider, message) => { if (mountedRef.current) { setSpeechProvider(provider); if (message) setNotice(message) } },
        (state, queued) => { if (mountedRef.current) { setPlayback(state); setQueuedSpeech(queued) } },
        (event) => { if (mountedRef.current) setTimings((items) => items.map((item) => item.id !== event.chunkId ? item :
          event.type === 'prepared' ? { ...item, browserPreparationMs: event.preparationMs } :
            { ...item, queueWaitMs: event.queueWaitMs, playbackStartDelayMs: event.playbackStartDelayMs, totalMs: durationMs(item.speechEndAtMs, event.startedAtMs) })) },
        () => { if (mountedRef.current) setPlaybackFailures((count) => count + 1) },
      )
      await connect(generation)
      if (generation !== generationRef.current) { socketRef.current?.close(); return }
      startedRef.current = true
      capture.resume()
      setStatus('listening')
    } catch (cause) {
      if (generation !== generationRef.current) return
      await stop(false, 'error')
      setError(cause instanceof Error ? cause.message : 'Could not start interpretation. Check the connection and retry.')
    } finally { startingRef.current = false }
  }

  const togglePause = () => {
    if (status === 'listening') {
      pausedRef.current = true
      captureRef.current?.pause()
      speechRef.current?.pause()
      setActivity(0)
      setStatus('paused')
    } else if (status === 'paused') {
      pausedRef.current = false
      captureRef.current?.resume()
      speechRef.current?.resume()
      setStatus('listening')
    }
  }

  const toggleOriginalMute = async (checked: boolean) => {
    if (captureRef.current && !captureRef.current.originalMuteSupported) return
    setMuteOriginal(checked)
    if (captureRef.current && !await captureRef.current.setOriginalMuted(checked)) {
      setMuteOriginal(!checked)
      setNotice('The browser could not change source-tab playback. Use the tab mute control if needed.')
    }
  }

  const sessionActive = !['idle', 'error', 'disconnected'].includes(status)
  const interpreting = ['connecting', 'listening', 'paused', 'reconnecting', 'stopping'].includes(status)
  const voiceAvailable = Boolean(window.speechSynthesis && typeof window.speechSynthesis.getVoices === 'function' && voiceForLanguage(voices, target))
  const sourceName = source === 'auto' ? 'Auto detect' : languageByCode(source).name
  const targetName = languageByCode(target).name
  const statusLabel = processing && status === 'listening' ? 'Processing' : status === 'permission' && mode === 'microphone' ? 'Requesting microphone permission' : statusLabels[status]
  const websocketStatus = status === 'connecting' || status === 'reconnecting'
    ? 'Connecting'
    : (status === 'listening' || status === 'paused') && socketRef.current?.isOpen()
      ? 'Connected'
      : 'Disconnected'

  return <section id="meeting" className="min-w-0 space-y-5" aria-label={mode === 'meeting' ? 'Meeting interpreter' : 'Microphone translator'}>
    <div className="flex flex-wrap gap-2" aria-label="Audio source"><Link to="/microphone" aria-current={mode === 'microphone' ? 'page' : undefined} className={mode === 'microphone' ? 'btn-primary' : 'btn-secondary'}><Mic2 size={16} />Microphone Translator</Link><Link to="/meeting" aria-current={mode === 'meeting' ? 'page' : undefined} className={mode === 'meeting' ? 'btn-primary' : 'btn-secondary'}><Radio size={16} />Meeting Listener</Link></div>
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">{mode === 'meeting' ? 'LOCAL MEETING LISTENER' : 'BROWSER MICROPHONE TRANSLATOR'}</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{mode === 'meeting' ? 'Meeting Interpreter' : 'Microphone Translator'}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted">{mode === 'meeting' ? 'Share the meeting browser tab with audio.' : 'Speak into the microphone you authorize.'} Complete phrases appear as captions and translated speech plays on this device only. Nothing is broadcast into a calling app.</p></div><div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2"><StatusIndicator label={statusLabel} tone={status === 'error' || status === 'disconnected' ? 'danger' : status === 'listening' ? 'success' : 'neutral'} /><span className="h-4 w-px bg-line" aria-hidden="true" /><StatusIndicator label={['listening', 'paused'].includes(status) ? 'Connected' : status === 'connecting' || status === 'reconnecting' ? 'Connecting' : 'Offline'} tone={['listening', 'paused'].includes(status) ? 'success' : 'neutral'} /></div></div>

    <Card className="p-4 sm:p-5"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-sm font-semibold">Session setup</h2><p className="mt-1 text-xs text-muted">{sourceName} → {targetName} · Text translation available</p></div><StatusIndicator label={speechProvider === 'azure' ? 'Azure speech playing' : speechProvider === 'browser' ? 'Browser speech playing' : voiceAvailable ? `${targetName} browser voice available` : 'Captions available'} tone={speechProvider === 'captions' && !voiceAvailable ? 'warning' : 'success'} /></div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2"><LanguageSelect id="meeting-source" label={mode === 'meeting' ? 'Meeting language' : 'Spoken language'} value={source} onChange={setSource} allowAuto disabled={interpreting} /><LanguageSelect id="meeting-target" label="Interpret" value={target} onChange={(value) => setTarget(value as Language)} disabled={interpreting} /></div>
      {mode === 'microphone' && <div className="mt-4"><label htmlFor="microphone-device" className="mb-1 block text-xs font-medium">Microphone</label><select id="microphone-device" value={deviceId} disabled={sessionActive} onChange={(event) => setDeviceId(event.target.value)} className="input w-full max-w-md"><option value="">Browser default microphone</option>{microphones.filter((device) => device.deviceId).map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label || 'Microphone (grant permission to see name)'}</option>)}</select><p className="mt-1 text-xs text-muted">Microphone permission is requested only when you press Start. Device names may appear after permission.</p></div>}
      <p className="mt-4 text-xs text-muted">Translated speech: Azure when enabled on the server, then a matching browser voice, then captions only. Active provider: {speechProvider === 'azure' ? 'Azure' : speechProvider === 'browser' ? 'Browser' : 'Captions only'}.</p>
      {interpreting && <p className="mt-2 text-xs text-muted">Stop the session to change languages.</p>}
      {!voiceAvailable && <p className="mt-2 text-xs text-[var(--color-warning)]">A compatible browser voice is unavailable. If Azure is also unavailable, translated captions will continue without speech.</p>}
      <div className="mt-5 grid gap-3 sm:grid-cols-2">{mode === 'meeting' && <label className="flex items-start gap-2 rounded-md border border-line p-3 text-sm"><input type="checkbox" checked={muteOriginal} disabled={Boolean(captureRef.current && !captureRef.current.originalMuteSupported)} onChange={(event) => void toggleOriginalMute(event.target.checked)} className="mt-0.5 accent-accent" /><span><span className="block font-medium">Mute original tab audio</span><span className="block text-xs leading-5 text-muted">Available only when your browser supports it.</span></span></label>}<label className="flex items-start gap-2 rounded-md border border-line p-3 text-sm"><input type="checkbox" checked={saveHistory} disabled={interpreting || !preferences?.save_history_enabled} onChange={(event) => setSaveHistory(event.target.checked)} className="mt-0.5 accent-accent" /><span><span className="block font-medium">Save translated text</span><span className="block text-xs leading-5 text-muted">Off by default. {preferences?.save_history_enabled ? 'Opt in for this session.' : <>Enable in <Link className="text-accent underline" to="/settings">Settings</Link> first.</>}</span></span></label><label className="flex items-start gap-2 rounded-md border border-line p-3 text-sm"><input type="checkbox" checked={muteTranslated} onChange={(event) => { setMuteTranslated(event.target.checked); if (event.target.checked) speechRef.current?.mute(); else if (status === 'listening') speechRef.current?.resume() }} className="mt-0.5 accent-accent" /><span><span className="block font-medium">Mute translated speech</span><span className="block text-xs leading-5 text-muted">Captions continue; queued speech stops.</span></span></label></div>
      <div className="mt-5 flex flex-wrap gap-2">{mode === 'meeting' && <Button type="button" onClick={() => void shareTab()} disabled={sessionActive || microphoneActive} className="w-full sm:w-auto"><Radio size={16} />Share browser tab with audio</Button>}<Button type="button" variant="primary" onClick={() => void start()} disabled={!['idle', 'error', 'disconnected', 'shared'].includes(status) || (mode === 'meeting' && microphoneActive)} className="w-full sm:w-auto"><Headphones size={16} />Start interpretation</Button><Button type="button" onClick={togglePause} disabled={status !== 'listening' && status !== 'paused'} className="flex-1 sm:flex-none">{status === 'paused' ? <Play size={16} /> : <Pause size={16} />}{status === 'paused' ? 'Resume' : 'Pause'}</Button><Button type="button" onClick={() => void stop()} disabled={!sessionActive || status === 'stopping'} className="flex-1 sm:flex-none"><Square size={15} />Stop session</Button><Button type="button" onClick={() => { setResults([]); setTimings([]) }} disabled={!results.length} className="w-full sm:w-auto">Clear captions</Button></div>
      <p className="mt-3 text-xs leading-5 text-muted">{mode === 'meeting' ? 'Choose a browser tab and enable “Share tab audio” in the permission prompt. TalkBuddy cannot capture another tab without your approval.' : 'Choose a microphone above, then press Start to request permission. Use headphones to reduce feedback.'} Audio is processed but not saved by default.</p>
      <div className="mt-4 flex flex-wrap items-center gap-4 border-t border-line pt-4 text-xs text-muted"><span className="flex items-center gap-2"><AudioLines size={15} />Audio activity</span><div role="meter" aria-label="Captured audio activity" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(activity * 100)} className="h-1.5 w-32 overflow-hidden rounded-full bg-raised"><div className="h-full rounded-full bg-accent transition-[width] duration-150" style={{ width: `${Math.round(activity * 100)}%` }} /></div><span>{activity > 0 && status === 'listening' ? 'Audio detected' : status === 'paused' ? 'Paused' : 'Waiting for audio'}</span><span className="flex items-center gap-1.5 sm:ml-auto">{playback === 'playing' ? <Volume2 size={15} /> : <VolumeX size={15} />}{muteTranslated ? 'Translated speech muted' : playback === 'playing' ? `Playing ${speechProvider} speech${queuedSpeech ? ` · ${queuedSpeech} queued` : ''}` : playback === 'paused' ? 'Playback paused' : voiceAvailable ? 'Playback idle' : 'Captions only if Azure is unavailable'}</span></div>
    </Card>

    <LatencyDiagnostics records={timings} connection={websocketStatus} capture={statusLabel} inputLevel={activity} capturedPhrases={capturedPhrases} phraseCount={phraseCount} processing={processing} processingErrors={processingErrors} droppedPhrases={droppedPhrases} droppedSamples={droppedSamples} bufferOverflows={bufferOverflows} websocketDisconnects={websocketDisconnects} playbackFailures={playbackFailures} queueDepth={queueDepth} playbackQueueDepth={queuedSpeech} onReset={() => { setTimings([]); setCapturedPhrases(0); setPhraseCount(0); setProcessingErrors(0); setDroppedPhrases(0); setDroppedSamples(0); setBufferOverflows(0); setWebsocketDisconnects(0); setPlaybackFailures(0) }} />
    {notice && <p role="status" className="rounded-lg border border-[var(--color-warning)] bg-[var(--color-warning-surface)] px-4 py-3 text-sm text-[var(--color-warning)]">{notice}</p>}
    {error && <ErrorMessage message={error} />}
    <div className="grid min-w-0 gap-4 md:grid-cols-2"><PhrasePanel title="Original speech" icon={<Captions size={17} className="text-muted" />} results={results} field="original" empty="Completed spoken phrases will appear here after transcription." pending={processing} /><PhrasePanel title="Translated speech" icon={<Volume2 size={17} className="text-accent" />} results={results} field="translated" empty="Translated captions will appear here. Playback requires a compatible browser voice." pending={processing} language={targetName} /></div>
  </section>
}
