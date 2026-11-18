import { useEffect, useState } from 'react'
import { Check, LogOut, Moon, Sun } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { LanguageSelect } from '../components/LanguageSelect'
import { PageHeading } from '../components/PageHeading'
import { Button, Card, ErrorMessage, LoadingState, StatusIndicator } from '../components/ui/Primitives'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { api } from '../lib/api'
import { languageByCode } from '../lib/languageRegistry'
import { voiceForLanguage } from '../lib/voices'
import type { Language, Preferences, SourceLanguage } from '../lib/types'

export function SettingsPage() {
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [signingOut, setSigningOut] = useState(false)
  const { theme, toggle } = useTheme()
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    let mounted = true
    setLoading(true); setError('')
    void api.preferences().then((value) => { if (mounted) setPreferences(value) })
      .catch((cause: unknown) => { if (mounted) setError(cause instanceof Error ? cause.message : 'Could not load settings.') })
      .finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [retry])

  useEffect(() => {
    const synth = window.speechSynthesis
    if (!synth?.getVoices) return
    const update = () => setVoices(synth.getVoices())
    update()
    synth.addEventListener?.('voiceschanged', update)
    return () => synth.removeEventListener?.('voiceschanged', update)
  }, [])

  const update = (change: Partial<Preferences>) => { setPreferences((current) => current ? { ...current, ...change } : current); setSaved(false) }
  const save = async () => {
    if (!preferences || saving) return
    setSaving(true); setSaved(false); setError('')
    try { setPreferences(await api.updatePreferences(preferences)); setSaved(true) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save settings.') }
    finally { setSaving(false) }
  }
  const signOut = async () => {
    if (signingOut) return
    setSigningOut(true); setError('')
    try { await logout(); navigate('/') }
    catch { setError('Could not sign out. Please retry.') }
    finally { setSigningOut(false) }
  }
  const voiceAvailable = preferences ? Boolean(voiceForLanguage(voices, preferences.target_language)) : false

  return <><PageHeading eyebrow="SETTINGS" title="Your preferences" description="Choose defaults for translation, playback, appearance, and saved history." />
    {error && <div className="mb-4 space-y-3"><ErrorMessage message={error} />{!preferences && <Button onClick={() => setRetry((value) => value + 1)}>Retry</Button>}</div>}
    {loading && !preferences ? <LoadingState label="Loading settings…" /> : <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,.85fr)]"><div className="min-w-0 space-y-4"><Card className="p-5"><h2 className="text-sm font-semibold">Language preferences</h2><p className="mt-1 text-xs text-muted">Used as defaults when you open a translation workspace.</p>{preferences && <div className="mt-5 grid gap-4 sm:grid-cols-2"><LanguageSelect id="settings-source" label="Default source" value={preferences.source_language} allowAuto onChange={(value: SourceLanguage) => update({ source_language: value })} /><LanguageSelect id="settings-target" label="Default target" value={preferences.target_language} onChange={(value) => update({ target_language: value as Language })} /></div>}</Card>
      <Card className="p-5"><h2 className="text-sm font-semibold">Audio and voice</h2><p className="mt-1 text-xs text-muted">Control the pace of browser speech playback.</p>{preferences && <><div className="mt-5 flex items-center justify-between gap-3"><label htmlFor="speech-rate" className="text-sm font-medium">Speech speed</label><output htmlFor="speech-rate" className="text-sm font-semibold text-accent">{preferences.speech_rate.toFixed(1)}×</output></div><input id="speech-rate" type="range" min="0.5" max="2" step="0.1" value={preferences.speech_rate} onChange={(event) => update({ speech_rate: Number(event.target.value) })} className="mt-4 w-full accent-accent" /><div className="mt-4"><StatusIndicator label={voiceAvailable ? `${languageByCode(preferences.target_language).name} voice available` : `${languageByCode(preferences.target_language).name} voice unavailable on this device`} tone={voiceAvailable ? 'success' : 'warning'} /></div></>}<p className="mt-3 text-xs leading-5 text-muted">Voice availability depends on your browser and operating system. Text translation works without a matching voice.</p></Card>
      <Card className="p-5"><h2 className="text-sm font-semibold">Privacy and history</h2><p className="mt-1 text-xs text-muted">Audio is never stored by the frontend.</p>{preferences && <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-line p-4"><input type="checkbox" checked={preferences.save_history_enabled} onChange={(event) => update({ save_history_enabled: event.target.checked })} className="mt-0.5 h-4 w-4 accent-accent" /><span><span className="block text-sm font-medium">Allow history saving</span><span className="mt-1 block text-xs leading-5 text-muted">You must still opt in for each translation or meeting session.</span></span></label>}<Link to="/history" className="mt-4 inline-block text-xs font-medium text-accent underline">View or delete saved history</Link></Card>
      {preferences && <div className="flex items-center justify-end gap-3">{saved && <span role="status" aria-label="Saved" className="inline-flex items-center gap-1 text-xs text-[var(--color-success)]"><Check size={15} />Saved</span>}<Button variant="primary" busy={saving} onClick={() => void save()}>Save changes</Button></div>}
    </div><div className="min-w-0 space-y-4"><Card className="p-5"><h2 className="text-sm font-semibold">Appearance</h2><p className="mt-1 text-xs text-muted">Theme changes are saved on this device.</p><div className="mt-5 grid grid-cols-2 gap-2"><button type="button" onClick={theme === 'dark' ? toggle : undefined} aria-pressed={theme === 'light'} className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-3 text-sm font-medium transition-colors duration-150 ${theme === 'light' ? 'border-accent bg-raised text-accent' : 'border-line text-muted hover:bg-raised'}`}><Sun size={16} />Light</button><button type="button" onClick={theme === 'light' ? toggle : undefined} aria-pressed={theme === 'dark'} className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-3 text-sm font-medium transition-colors duration-150 ${theme === 'dark' ? 'border-accent bg-raised text-accent' : 'border-line text-muted hover:bg-raised'}`}><Moon size={16} />Dark</button></div></Card>
      <Card className="p-5"><h2 className="text-sm font-semibold">Account</h2><p className="mt-1 text-xs text-muted">Your signed-in TalkBuddy account.</p><dl className="mt-5 space-y-3 text-sm"><div><dt className="text-xs text-muted">Name</dt><dd className="mt-1 break-words font-medium">{user?.name || 'Unavailable'}</dd></div><div><dt className="text-xs text-muted">Email</dt><dd className="mt-1 break-all font-medium">{user?.email || 'Unavailable'}</dd></div></dl><Button className="mt-5" onClick={() => void signOut()} busy={signingOut}><LogOut size={16} />Sign out</Button></Card></div></div>}
  </>
}
