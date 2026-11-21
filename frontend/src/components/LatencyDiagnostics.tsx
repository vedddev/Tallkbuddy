import { Download, RotateCcw } from 'lucide-react'
import { latencySummary, timingCsv, type PhraseTimingRecord } from '../lib/latency'

function displayMs(value: number | null): string {
  if (value === null) return 'Unavailable'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`
}

export function LatencyDiagnostics({ records, connection, onReset, capture = 'Idle', inputLevel = 0, capturedPhrases = 0, phraseCount = 0, processing = false, processingErrors = 0, droppedPhrases = 0, droppedSamples = 0, bufferOverflows = 0, websocketDisconnects = 0, playbackFailures = 0, queueDepth = 0, playbackQueueDepth = 0 }: {
  records: PhraseTimingRecord[]
  connection: string
  onReset: () => void
  capture?: string
  inputLevel?: number
  capturedPhrases?: number
  phraseCount?: number
  processing?: boolean
  processingErrors?: number
  droppedPhrases?: number
  droppedSamples?: number
  bufferOverflows?: number
  websocketDisconnects?: number
  playbackFailures?: number
  queueDepth?: number
  playbackQueueDepth?: number
}) {
  const downloadTimings = () => {
    if (!records.length) return
    const url = URL.createObjectURL(new Blob([timingCsv(records)], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'talkbuddy-phrase-timings.csv'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  const summary = latencySummary(records)
  const latest = records.at(-1)
  const metrics = [
    ['Captured phrase duration', latest?.captureDurationMs ?? null, 'Browser'],
    ['Phrase encoding', latest?.encodingMs ?? null, 'Browser'],
    ['Speech end to submission', latest?.speechEndToSubmitMs ?? null, 'Browser estimate'],
    ['Speech end to caption', latest?.captionMs ?? null, 'Browser estimate'],
    ['WebSocket round trip', latest?.roundTripMs ?? null, 'Browser'],
    ['STT call duration', latest?.sttMs ?? null, 'Server'],
    ['Translation call duration', latest?.translationMs ?? null, 'Server'],
    ['Total server processing', latest?.serverProcessingMs ?? null, 'Server'],
    ['Azure speech preparation', latest?.ttsMs ?? null, 'Server'],
    ['Browser speech preparation', latest?.browserPreparationMs ?? null, 'Browser'],
    ['Playback queue wait', latest?.queueWaitMs ?? null, 'Browser'],
    ['Playback start delay', latest?.playbackStartDelayMs ?? null, 'Browser'],
  ] as const
  return <details className="panel min-w-0 overflow-hidden">
    <summary className="cursor-pointer px-4 py-3 text-sm font-medium marker:text-muted sm:px-5">
      Diagnostics <span className="ml-2 text-xs font-normal text-muted">Last speech end to playback: {displayMs(summary.lastMs)}</span>
    </summary>
    <div className="border-t border-line px-4 pb-4 pt-3 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>Connection: {connection} · {records.length} recent phrase{records.length === 1 ? '' : 's'} · {summary.completeCount} with playback timing</span>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-secondary" onClick={downloadTimings} disabled={!records.length}><Download size={14} aria-hidden="true" />Download timings</button>
          <button type="button" className="btn-secondary" onClick={onReset} disabled={!records.length && !capturedPhrases && !phraseCount && !processingErrors && !droppedPhrases && !droppedSamples && !bufferOverflows && !websocketDisconnects && !playbackFailures}><RotateCcw size={14} aria-hidden="true" />Reset</button>
        </div>
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['Capture', capture], ['Processing', processing ? 'Yes' : 'No'],
          ['Relative input activity', `${Math.round(inputLevel * 100)}%`], ['Captured phrases', capturedPhrases], ['Phrases accepted', phraseCount],
          ['WebSocket queue', `${queueDepth}/4`], ['Playback queue', `${playbackQueueDepth}/8`],
          ['Processing errors', processingErrors], ['Dropped phrases', droppedPhrases],
          ['Dropped audio samples', droppedSamples], ['Buffer overflows', bufferOverflows],
          ['WebSocket disconnects', websocketDisconnects], ['Playback failures', playbackFailures],
        ].map(([label, value]) => <div key={label} className="rounded-lg bg-raised p-2"><dt className="text-muted">{label}</dt><dd className="mt-0.5 font-medium text-foreground">{value}</dd></div>)}
      </dl>
      {!latest ? <p className="mt-3 text-sm text-muted">No phrase timings yet. Start interpreting to collect measurements in memory.</p> : <>
        <p className="mt-3 break-all text-xs text-muted">Last phrase: {latest.phraseId ?? 'Unavailable'} · Socket chunk: {latest.serverChunkId} · Capture started: {latest.captureStartedAtMs === null ? 'Unavailable' : 'Measured locally'} · Speech onset: {latest.speechStartAtMs === null ? 'Unavailable' : 'Estimated locally'}</p>
        <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Caption average', summary.captionAverageMs],
            ['Caption p50', summary.captionP50Ms],
            ['Caption p95', summary.captionP95Ms],
            ['Playback average', summary.averageMs],
            ['Playback p50', summary.p50Ms],
            ['Playback p95', summary.p95Ms],
          ].map(([label, value]) => <div key={label} className="rounded-lg bg-raised p-3"><dt className="text-muted">{label}</dt><dd className="mt-1 text-sm font-semibold text-foreground">{displayMs(value as number | null)}</dd></div>)}
        </dl>
        <dl className="mt-4 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          {metrics.map(([label, value, origin]) => <div key={label} className="flex min-w-0 justify-between gap-3 border-b border-line py-1.5"><dt className="min-w-0 text-muted">{label} <span className="sr-only">({origin})</span></dt><dd className="shrink-0 font-medium text-foreground">{displayMs(value)}</dd></div>)}
        </dl>
        <p className="mt-3 text-xs leading-5 text-muted">Browser and server durations use separate monotonic clocks. Speech onset/end are estimated from the detected pause. Playback start requires a browser speech start event; missing voice or events leave it unavailable. Statistics include only measured phrases. Dropped audio samples indicate main-thread overload; an affected phrase is discarded.</p>
      </>}
    </div>
  </details>
}
