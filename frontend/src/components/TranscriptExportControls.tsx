import { useMemo, useState } from 'react'
import { Button, Card } from './ui/Primitives'
import { transcriptFileName, transcriptPrintHtml, transcriptSrt, transcriptTxt, type TranscriptEntry, type TranscriptSelection, type TranscriptSession } from '../lib/transcriptExport'

interface Props { session: TranscriptSession | null; entries: TranscriptEntry[]; truncated: number }

function download(text: string, fileName: string, mime: string): void {
  const url = URL.createObjectURL(new Blob(['\uFEFF', text], { type: `${mime};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function TranscriptExportControls({ session, entries, truncated }: Props) {
  const [selection, setSelection] = useState<TranscriptSelection>('bilingual')
  const [notice, setNotice] = useState('')
  const srt = useMemo(() => session ? transcriptSrt(entries, session, selection) : null, [entries, session, selection])
  const hasCaptions = Boolean(session && entries.some((entry) => entry.sessionId === session.id))
  const save = (format: 'txt' | 'srt') => {
    if (!session || !hasCaptions) return
    if (format === 'srt') {
      if (!srt?.text) { setNotice('No timed captions are available for this SRT selection. Use TXT or PDF for untimed phrases.'); return }
      download(srt.text, transcriptFileName(session, 'srt'), 'application/x-subrip')
      setNotice(srt.skippedUntimed || srt.skippedNoText ? `SRT saved. ${srt.skippedUntimed} untimed and ${srt.skippedNoText} untranslated phrases were omitted.` : 'SRT saved.')
    } else {
      download(transcriptTxt(entries, session, selection), transcriptFileName(session, 'txt'), 'text/plain')
      setNotice('TXT saved to your device.')
    }
  }
  const printPdf = () => {
    if (!session || !hasCaptions) return
    const popup = window.open('', '_blank')
    if (!popup) { setNotice('Your browser blocked the print window. Allow pop-ups for TalkBuddy and try again.'); return }
    popup.opener = null
    popup.document.open()
    popup.document.write(transcriptPrintHtml(entries, session, selection))
    popup.document.close()
    void popup.document.fonts?.ready.then(() => { if (!popup.closed) { popup.focus(); popup.print() } })
    if (!popup.document.fonts) { popup.focus(); popup.print() }
    setNotice('Choose Save as PDF in your browser print dialog. Check Devanagari text in the preview.')
  }
  return <Card className="min-w-0 p-4 sm:p-5" aria-label="Transcript export">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">Export meeting transcript</h2><p className="mt-1 text-xs text-muted">Finalized captions on this device only. Export does not enable or upload history.</p></div><span className="text-xs text-muted">{entries.length} phrases</span></div>
    <div className="mt-4 flex flex-wrap items-end gap-3"><label className="min-w-[180px] text-xs font-medium" htmlFor="transcript-content">Content<select id="transcript-content" className="input mt-1 w-full" value={selection} onChange={(event) => { setSelection(event.target.value as TranscriptSelection); setNotice('') }}><option value="bilingual">Bilingual</option><option value="original">Original only</option><option value="translated">Translated only</option></select></label><Button type="button" disabled={!hasCaptions} onClick={() => save('txt')}>Download TXT</Button><Button type="button" disabled={!hasCaptions} onClick={() => save('srt')}>Download SRT</Button><Button type="button" disabled={!hasCaptions} onClick={printPdf}>Print / Save PDF</Button></div>
    {truncated > 0 && <p className="mt-3 text-xs text-[var(--color-warning)]">{truncated} older phrases are no longer in memory and will not be exported.</p>}
    {srt && hasCaptions && (srt.skippedUntimed > 0 || srt.skippedNoText > 0) && <p className="mt-3 text-xs text-muted">SRT requires real speech start and end timing. It will omit {srt.skippedUntimed} untimed and {srt.skippedNoText} phrases without {selection === 'translated' ? 'translation' : 'text'}.</p>}
    {notice && <p role="status" className="mt-3 text-xs text-muted">{notice}</p>}
  </Card>
}
