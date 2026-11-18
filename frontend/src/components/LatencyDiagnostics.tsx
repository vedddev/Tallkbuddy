import { RotateCcw } from 'lucide-react'
import { latencySummary, type PhraseTimingRecord } from '../lib/latency'

function displayMs(value: number | null): string {
  if (value === null) return 'Unavailable'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`
}

export function LatencyDiagnostics({ records, connection, onReset }: {
  records: PhraseTimingRecord[]
  connection: string
  onReset: () => void
}) {
  const summary = latencySummary(records)
  const latest = records.at(-1)
  const metrics = [
    ['Captured phrase duration', latest?.captureDurationMs ?? null, 'Browser'],
    ['Speech end to submission', latest?.speechEndToSubmitMs ?? null, 'Browser estimate'],
    ['WebSocket round trip', latest?.roundTripMs ?? null, 'Browser'],
    ['STT call duration', latest?.sttMs ?? null, 'Server'],
    ['Translation call duration', latest?.translationMs ?? null, 'Server'],
    ['Total server processing', latest?.serverProcessingMs ?? null, 'Server'],
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
        <button type="button" className="btn-secondary" onClick={onReset} disabled={!records.length}><RotateCcw size={14} aria-hidden="true" />Reset</button>
      </div>
      {!latest ? <p className="mt-3 text-sm text-muted">No phrase timings yet. Start interpreting to collect measurements in memory.</p> : <>
        <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Last phrase', summary.lastMs],
            ['Average', summary.averageMs],
            ['p50', summary.p50Ms],
            ['p95', summary.p95Ms],
          ].map(([label, value]) => <div key={label} className="rounded-lg bg-raised p-3"><dt className="text-muted">{label}</dt><dd className="mt-1 text-sm font-semibold text-foreground">{displayMs(value as number | null)}</dd></div>)}
        </dl>
        <dl className="mt-4 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          {metrics.map(([label, value, origin]) => <div key={label} className="flex min-w-0 justify-between gap-3 border-b border-line py-1.5"><dt className="min-w-0 text-muted">{label} <span className="sr-only">({origin})</span></dt><dd className="shrink-0 font-medium text-foreground">{displayMs(value)}</dd></div>)}
        </dl>
        <p className="mt-3 text-xs leading-5 text-muted">Browser and server durations use separate monotonic clocks. Speech end is estimated from the detected pause. Playback start requires a browser speech start event; missing voice or events leave it unavailable. Statistics include only phrases with playback timing.</p>
      </>}
    </div>
  </details>
}
