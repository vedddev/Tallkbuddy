import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { MeetingInterpreter } from '../components/MeetingInterpreter'
import * as meetingAudio from '../lib/meetingAudio'
import { TranslationSocket } from '../lib/socket'
import { languageRegistry } from '../lib/languageRegistry'
import { reconnectDelayMs } from '../components/MeetingInterpreter'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('bounds exponential reconnect delay with jitter', () => {
  expect(reconnectDelayMs(0, 0)).toBe(800)
  expect(reconnectDelayMs(1, 0.5)).toBe(2000)
  expect(reconnectDelayMs(2, 1)).toBe(4000)
  expect(reconnectDelayMs(50, 1)).toBe(4000)
})

it('pauses on a dropped connection, reconnects once, and never replays the old phrase', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0)
  const capture = { pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined), setOriginalMuted: vi.fn().mockResolvedValue(false), originalMuteSupported: false }
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockResolvedValue(capture)
  class FakeWebSocket {
    static OPEN = 1
    static instances: FakeWebSocket[] = []
    readyState = 0
    sent: (string | ArrayBuffer)[] = []
    onopen: (() => void) | null = null
    onmessage: ((event: { data: string }) => void) | null = null
    onclose: ((event: { code: number }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(_url: string) { FakeWebSocket.instances.push(this) }
    send(value: string | ArrayBuffer) { this.sent.push(value) }
    close() { this.readyState = 3; this.onclose?.({ code: 1000 }) }
    open() { this.readyState = 1; this.onopen?.() }
    receive(value: object) { this.onmessage?.({ data: JSON.stringify(value) }) }
  }
  vi.stubGlobal('WebSocket', FakeWebSocket)
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
  await act(async () => { FakeWebSocket.instances[0].open(); FakeWebSocket.instances[0].receive({ type: 'ready', target_language: 'hi', source_language: null, audio_format: 'wav' }) })
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  act(() => FakeWebSocket.instances[0].close())
  expect(screen.getByRole('status', { name: 'Reconnecting' })).toBeInTheDocument()
  fireEvent.click(screen.getByText(/Diagnostics/))
  expect(screen.getByText('WebSocket disconnects').nextElementSibling).toHaveTextContent('1')
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2), { timeout: 2500 })
  await act(async () => { FakeWebSocket.instances[1].open(); FakeWebSocket.instances[1].receive({ type: 'ready', target_language: 'hi', source_language: null, audio_format: 'wav' }) })
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  expect(capture.pause).toHaveBeenCalled()
  expect(capture.resume).toHaveBeenCalledTimes(2)
  expect(FakeWebSocket.instances[1].sent).toHaveLength(1)
})

it('starts microphone mode only after a click, uses the selected device, and stops capture', async () => {
  const capture = { pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined), setOriginalMuted: vi.fn().mockResolvedValue(false), originalMuteSupported: false }
  const startCapture = vi.spyOn(meetingAudio, 'startMicrophoneCapture').mockResolvedValue(capture)
  vi.spyOn(TranslationSocket.prototype, 'connect').mockResolvedValue(undefined)
  vi.spyOn(TranslationSocket.prototype, 'stop').mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { enumerateDevices: vi.fn().mockResolvedValue([{ kind: 'audioinput', deviceId: 'mic-1', label: 'USB microphone' }]) } })
  render(<MemoryRouter><MeetingInterpreter mode="microphone" preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  expect(startCapture).not.toHaveBeenCalled()
  await waitFor(() => expect(screen.getByRole('option', { name: 'USB microphone' })).toBeInTheDocument())
  fireEvent.change(screen.getByLabelText('Microphone'), { target: { value: 'mic-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(startCapture).toHaveBeenCalledWith(expect.any(Function), expect.any(Function), expect.any(Function), 'mic-1', expect.any(Function), expect.any(Function)))
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  expect(capture.pause).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
  fireEvent.click(screen.getByRole('button', { name: 'Stop session' }))
  await waitFor(() => expect(capture.stop).toHaveBeenCalledOnce())
})

it('shows microphone permission denial and does not connect', async () => {
  vi.spyOn(meetingAudio, 'startMicrophoneCapture').mockRejectedValue(new Error('Microphone access was denied. Allow microphone access in browser site settings and try again.'))
  const connect = vi.spyOn(TranslationSocket.prototype, 'connect')
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { enumerateDevices: vi.fn().mockResolvedValue([]) } })
  render(<MemoryRouter><MeetingInterpreter mode="microphone" preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Microphone access was denied'))
  expect(connect).not.toHaveBeenCalled()
})

it('asks for tab capture from Start and shows a useful permission error', async () => {
  const getDisplayMedia = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getDisplayMedia } })
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Tab sharing was denied'))
  expect(getDisplayMedia).toHaveBeenCalledOnce()
  expect(getDisplayMedia).toHaveBeenCalledWith(expect.objectContaining({ video: expect.any(Object), audio: expect.any(Object) }))
})

it('keeps the selected language and sends it through the WebSocket configuration', async () => {
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockResolvedValue({
    pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined),
    setOriginalMuted: vi.fn().mockResolvedValue(true), originalMuteSupported: true,
  })
  const connect = vi.spyOn(TranslationSocket.prototype, 'connect').mockResolvedValue(undefined)
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  const target = screen.getByLabelText('Interpret') as HTMLSelectElement
  const options = Array.from(target.options).filter((option) => option.value !== 'auto')
  expect(options.map((option) => option.value)).toEqual(languageRegistry.map((entry) => entry.code))
  expect(options.every((option) => !option.disabled)).toBe(true)
  fireEvent.change(target, { target: { value: 'zh-CN' } })
  fireEvent.change(screen.getByLabelText('Meeting language'), { target: { value: 'auto' } })
  expect(target.value).toBe('zh-CN')
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(connect).toHaveBeenCalledOnce())
  expect(connect.mock.calls[0][0]).toMatchObject({ target_language: 'zh-CN', source_language: 'auto' })
})

it('keeps translated captions visible when the selected browser voice is missing', async () => {
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockResolvedValue({
    pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined),
    setOriginalMuted: vi.fn().mockResolvedValue(true), originalMuteSupported: true,
  })
  Object.assign(window.speechSynthesis, { getVoices: () => [], pause: vi.fn(), resume: vi.fn() })
  class FakeWebSocket {
    static OPEN = 1
    static latest: FakeWebSocket
    readyState = 0
    onopen: (() => void) | null = null
    onmessage: ((event: { data: string }) => void) | null = null
    onclose: ((event: { code: number }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(_url: string) { FakeWebSocket.latest = this }
    send(_payload: string | ArrayBuffer) {}
    close() { this.readyState = 3; this.onclose?.({ code: 1000 }) }
    open() { this.readyState = 1; this.onopen?.() }
    receive(message: object) { this.onmessage?.({ data: JSON.stringify(message) }) }
  }
  vi.stubGlobal('WebSocket', FakeWebSocket)
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Interpret'), { target: { value: 'ja' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(FakeWebSocket.latest).toBeDefined())
  await act(async () => {
    FakeWebSocket.latest.open()
    FakeWebSocket.latest.receive({ type: 'ready', target_language: 'ja', source_language: 'en', audio_format: 'wav' })
  })
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  act(() => FakeWebSocket.latest.receive({ type: 'processing', chunk_id: 1 }))
  expect(screen.getByRole('status', { name: 'Processing' })).toBeInTheDocument()
  const longTranslation = 'おはようございます。'.repeat(50)
  const longOriginal = '这是一个完整的句子。'.repeat(50)
  act(() => FakeWebSocket.latest.receive({
    type: 'result', chunk_id: 1, original: longOriginal, translated: longTranslation,
    detected_language: 'en', target_language: 'ja', processing_time_ms: 20,
  }))
  act(() => FakeWebSocket.latest.receive({ type: 'speech_error', chunk_id: 1, code: 'speech_unavailable', message: 'Translated speech is unavailable' }))
  expect(screen.getByText(longTranslation)).toHaveClass('break-words')
  expect(screen.getByText(longOriginal)).toBeInTheDocument()
  expect(screen.getByText(/Completed phrase 1 · English/)).toBeInTheDocument()
  expect(screen.getAllByText(/Received /)).toHaveLength(2)
  expect(screen.getByText(/No matching browser voice is installed/)).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument()
  const translatedList = screen.getByRole('list', { name: 'Translated speech' })
  Object.defineProperty(translatedList, 'scrollHeight', { configurable: true, value: 1000 })
  Object.defineProperty(translatedList, 'clientHeight', { configurable: true, value: 200 })
  translatedList.scrollTop = 100
  fireEvent.scroll(translatedList)
  act(() => FakeWebSocket.latest.receive({ type: 'result', chunk_id: 2, original: 'धन्यवाद', translated: 'ありがとうございます', detected_language: 'mr', language_detection_source: 'stt', target_language: 'ja', processing_time_ms: 20 }))
  expect(screen.getByText(/Completed phrase 2 · Marathi/)).toBeInTheDocument()
  act(() => FakeWebSocket.latest.receive({ type: 'result', chunk_id: 3, original: 'Unknown source', translated: '訳', detected_language: null, language_detection_source: 'unknown', target_language: 'ja', processing_time_ms: 20 }))
  expect(screen.getByText(/Completed phrase 3 · Unknown language/)).toBeInTheDocument()
  expect(translatedList.scrollTop).toBe(100)
  await act(async () => FakeWebSocket.latest.receive({ type: 'error', code: 'provider_unavailable', message: 'AI service failed', recoverable: false, chunk_id: 4, original: 'Original survives', detected_language: 'en', language_detection_source: 'stt' }))
  expect(screen.getByRole('alert')).toHaveTextContent('AI translation is temporarily unavailable')
  expect(screen.getByText('Original survives')).toBeInTheDocument()
  expect(screen.getByText('Translation unavailable for this phrase.')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'Error' })).toBeInTheDocument()
  expect(screen.getByText(longTranslation)).toBeInTheDocument()
})

it('shares a tab first, then starts, pauses, resumes, and stops without duplicate starts', async () => {
  const capture = {
    pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined),
    setOriginalMuted: vi.fn().mockResolvedValue(true), originalMuteSupported: true,
  }
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockResolvedValue(capture)
  const connect = vi.spyOn(TranslationSocket.prototype, 'connect').mockResolvedValue(undefined)
  vi.spyOn(TranslationSocket.prototype, 'stop').mockResolvedValue(undefined)
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Share browser tab with audio' }))
  await waitFor(() => expect(screen.getByRole('status', { name: 'Tab shared' })).toBeInTheDocument())
  expect(connect).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Interpret'), { target: { value: 'mr' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(screen.getByRole('status', { name: 'Listening' })).toBeInTheDocument())
  expect(connect).toHaveBeenCalledTimes(1)
  expect(connect.mock.calls[0][0].target_language).toBe('mr')
  expect(screen.getByLabelText('Interpret')).toBeDisabled()
  expect(capture.resume).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  expect(screen.getByRole('status', { name: 'Paused' })).toBeInTheDocument()
  expect(capture.pause).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
  expect(capture.resume).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Stop session' }))
  await waitFor(() => expect(capture.stop).toHaveBeenCalledOnce())
  expect(screen.getByRole('status', { name: 'Idle' })).toBeInTheDocument()
})

it('shows missing tab audio and connection failures while cleaning up capture', async () => {
  const capture = { pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined), setOriginalMuted: vi.fn().mockResolvedValue(true), originalMuteSupported: true }
  const startCapture = vi.spyOn(meetingAudio, 'startMeetingCapture').mockRejectedValueOnce(new Error('No tab audio was shared. Select a browser tab and enable Share tab audio.')).mockResolvedValue(capture)
  vi.spyOn(TranslationSocket.prototype, 'connect').mockRejectedValue(new Error('Unable to connect to translation. Check that the backend is running.'))
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No tab audio was shared'))
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  await waitFor(() => expect(startCapture).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Unable to connect to translation'))
  expect(capture.stop).toHaveBeenCalledOnce()
  expect(screen.getByRole('status', { name: 'Error' })).toBeInTheDocument()
})

it('shows permission-request state and a specific session authentication failure', async () => {
  let grant!: (capture: meetingAudio.MeetingCapture) => void
  const capture = { pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined), setOriginalMuted: vi.fn().mockResolvedValue(true), originalMuteSupported: true }
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockReturnValue(new Promise((resolve) => { grant = resolve }))
  vi.spyOn(TranslationSocket.prototype, 'connect').mockRejectedValue(new Error('Your session expired. Sign in again.'))
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Start interpretation' }))
  expect(screen.getByRole('status', { name: 'Requesting tab permission' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start interpretation' })).toBeDisabled()
  await act(async () => grant(capture))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Your session expired'))
  expect(capture.stop).toHaveBeenCalledOnce()
})

it('warns when original-tab muting is unsupported and keeps captions mode available', async () => {
  vi.spyOn(meetingAudio, 'startMeetingCapture').mockResolvedValue({
    pause: vi.fn(), resume: vi.fn(), stop: vi.fn().mockResolvedValue(undefined),
    setOriginalMuted: vi.fn().mockResolvedValue(false), originalMuteSupported: false,
  })
  render(<MemoryRouter><MeetingInterpreter preferences={null} microphoneActive={false} onActiveChange={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByRole('checkbox', { name: /Mute original tab audio/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Share browser tab with audio' }))
  await waitFor(() => expect(screen.getByText(/cannot mute the source tab/)).toBeInTheDocument())
  expect(screen.getByRole('checkbox', { name: /Mute original tab audio/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Start interpretation' })).toBeEnabled()
})
