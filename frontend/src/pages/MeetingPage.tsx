import { useEffect, useState } from 'react'
import { MeetingInterpreter } from '../components/MeetingInterpreter'
import { ErrorMessage, LoadingState } from '../components/ui/Primitives'
import { api } from '../lib/api'
import type { Preferences } from '../lib/types'

export function MeetingPage({ mode = 'meeting' }: { mode?: 'meeting' | 'microphone' }) {
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let mounted = true
    api.preferences().then((value) => { if (mounted) setPreferences(value) })
      .catch(() => { if (mounted) setError('Could not load your saved preferences. You can still interpret without saving history.') })
      .finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [])
  return <div className="min-w-0 space-y-4">
    {error && <ErrorMessage message={error} />}
    {loading ? <LoadingState label="Loading audio settings…" /> : <MeetingInterpreter key={mode} mode={mode} preferences={preferences} microphoneActive={false} onActiveChange={() => undefined} />}
  </div>
}
