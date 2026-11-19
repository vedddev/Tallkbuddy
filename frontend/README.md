# TalkBuddy frontend

React, TypeScript, Vite, Tailwind CSS, React Router, and Lucide React. The frontend lives entirely in `frontend/` and uses the existing FastAPI endpoints.

## Run locally

Start the backend from `backend/` with its PostgreSQL configuration, migrations, and `GROQ_API_KEY` configured:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload --ws websockets --ws-max-size 1048576 --ws-max-queue 4
```

In a second PowerShell window, from `frontend/`:

```powershell
Copy-Item .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. `VITE_BACKEND_URL` is the Vite development proxy target (`http://127.0.0.1:8000` by default). The browser calls same-origin `/api` and `/ws` paths, so it can read the non-HTTP-only CSRF cookie while the session cookie stays HTTP-only. FastAPI accepts both `http://127.0.0.1:5173` and `http://localhost:5173` in development. Use the same hostname consistently in the browser. Restart FastAPI after changing its `.env`. `VITE_API_BASE_URL` is optional and should point to the same public origin as the frontend; a separate cross-site origin will not expose the CSRF cookie to the frontend.

## Build and test

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

`dist/` contains the production bundle. Serve it over HTTPS and reverse-proxy `/api` and `/ws` to FastAPI on the **same public origin**. Ensure your proxy forwards WebSocket upgrades and bounds upload and frame sizes. The backend session cookie is `Secure` in production. Never put Groq keys or database credentials in Vite variables; `VITE_` variables are public build-time values.

The [shared language registry](../shared/languages.json) defines ten canonical codes with separate Whisper language hints and browser speech tags. All ten are accepted by FastAPI and appear in the meeting listener, workspace, and settings selectors. Existing language codes remain unchanged, and automatic source detection remains available. Chinese Mandarin uses `zh-CN` in TalkBuddy and `zh` when a source-language hint is sent to Whisper. Browser voice availability is device-specific; a language remains selectable for captions even if its voice is missing.

## Application routes

- `/overview` shows quick actions, up to five recent saved sessions, and **API reachability** from `/api/health`. This status does not test Groq or PostgreSQL.
- `/translate` is the text translation workspace. The backend text endpoint detects the source language automatically; its source selector labels the input and enables swapping, but is not sent as a source hint. Saving requires the account preference and a per-translation opt-in.
- `/microphone` is the browser microphone translator; `/meeting` is the local meeting-tab listener. Both use the same phrase capture and WebSocket pipeline. `/history` and `/settings` retain their existing functions.
- `/workspace` remains the legacy microphone workspace for old links. Legacy `/workspace#translate` and `/workspace#meeting` URLs redirect to `/translate` and `/meeting` respectively. Leaving either active browser audio route releases capture and speech playback.

History search and language filters apply to the currently loaded page of 20 sessions. The backend history API supports pagination but has no search or filter parameters, so the UI labels this scope explicitly.

## Manual frontend QA

Use browser responsive mode at 375, 768, 1280, and 1920 CSS pixels. Repeat in light and dark themes. Check the landing, login, register, overview, translate, meeting, history, settings, and legacy microphone workspace routes for horizontal scrolling, clipped controls, readable labels, and visible keyboard focus. For protected pages, sign in using a local development account.

- Submit login and registration with invalid and valid fields; use Tab, Shift+Tab, Enter, and the password visibility button. Confirm error and loading states.
- Open the mobile navigation drawer, cycle focus, close with Escape, and navigate to another route. Check that the theme preference survives reload.
- On Translate, enter long Hindi, Marathi, Japanese, Korean, and Chinese text; check wrapping, copy, speech, missing-voice errors, and a failed API request. The source selector is a label and swap aid; the text API detects source language itself.
- On History, test no results, a failed load, page changes, current-page search and filters, details, and deletion confirmation. Verify timestamps remain visible on mobile.
- On Live Meeting, verify Start, Pause, Resume, and Stop at mobile width, tab permission rejection, missing audio track, disconnect, captions, voice warning, and cleanup after navigation. Repeat on `/microphone` with a physical microphone, microphone permission denial, device unplugging, and mute/unmute. Local playback does not broadcast into Google Meet.

Automated frontend tests cover core behavior, but browser capture, installed voices, provider responses, and exact visual layout require this manual check on the target browser and device.

## How translation works

The microphone workspace records mono samples with `AudioWorklet`, resamples to 16 kHz, and encodes each 1.25-second segment as a complete PCM WAV file. The socket sends one chunk at a time and keeps at most three waiting chunks in arrival order; new chunks are dropped if the provider falls behind. Stopping flushes the final microphone segment if it is at least 0.25 seconds. Disconnects stop microphone tracks and show a reconnect action. Reconnecting starts a new saved session when history is enabled.

History requires enabling `save_history_enabled` in Settings **and** checking “Save this conversation” in the workspace. The frontend creates and ends the backend translation session, sends a UUID `request_id` before each saved WAV chunk, and keeps unsaved results only in page memory. Text translation uses the existing REST endpoint and an `Idempotency-Key` when saving. Browser playback uses `speechSynthesis`; available voices vary by device. Raw audio is never saved by the frontend.

Microphone recording requires a secure context (`localhost` or HTTPS) and a browser with `AudioWorklet`. WebSocket results are chunk-based and may arrive with provider latency; this is not continuous streaming. If a user navigates away during an in-flight chunk, the socket closes and that incomplete chunk may not produce a result.

## Browser audio modes

`/microphone` uses `getUserMedia` only after Start is pressed. The device selector lists microphone inputs when the browser exposes them; names may be hidden before permission. A selected device uses an exact device ID and an unavailable device produces an error rather than silently changing inputs. An empty selection uses the browser's current default input. `/meeting` uses `getDisplayMedia` and requires the user to choose a browser tab with audio. Browser support for tab audio varies by operating system, browser version, and sharing choice. Both modes require a secure context (localhost or HTTPS), AudioWorklet, an authenticated session, and a live backend. Stop, track ending, or leaving the route releases audio tracks and the audio context.

Both modes reuse the same energy-based VAD and send complete mono 16 kHz PCM WAV phrases under 1 MiB over `/ws/translate`. An AudioWorklet averages stereo channels without gain, batches about 20 ms at the browser's native AudioContext rate, and allows only one unacknowledged block to reach the page. If the page stalls, the worklet drops samples and the VAD resets the partial phrase; Diagnostics counts these samples. The encoder avoids resampling when capture is already 16 kHz and averages input samples when downsampling common 44.1/48 kHz capture rates. This reduces aliasing but is not a studio-quality resampler. An unsupported AudioWorklet produces a clear error. They send one phrase at a time with at most three waiting phrases; skipped phrases are not retried after reconnect. Captions are kept in memory, limited to 30 results, and may be cleared in the UI. Translation history remains off unless enabled in Settings and explicitly selected for a session. TalkBuddy does not store raw browser audio. Use headphones during microphone translation to reduce acoustic feedback from local translated speech; browser echo cancellation is requested for microphone capture but cannot guarantee removal of translated playback.

Browser voice playback is the default. It requires an installed voice matching the selected target language; captions continue if one is absent. **Azure speech** is an explicit alternative that sends `synthesize_speech:true` through the same authenticated WebSocket. It requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` in the private backend `.env`. When unavailable, the connection reports an error and the user can select Browser voice. Generated 24 kHz mono PCM WAV is validated and placed in a bounded local playback queue. Stop and mute cancel pending playback. Browser autoplay restrictions can prevent audio until the user interacts with the page. No speech audio is sent to Google Meet or Zoom. The optional [desktop bridge](../desktop_bridge/README.md) and VB-CABLE are experimental, Windows-specific tools and are not required by the browser product.

The legacy `/workspace` microphone path still uses fixed 1.25-second chunks. Use `/microphone` for pause-based phrase capture. Browser capture and playback require manual device testing; the automated suite uses mocks and does not establish hardware or calling-app compatibility.

## Local meeting listener

### Latency diagnostics

Expand **Diagnostics** on `/meeting` or `/microphone` to see separate speech-end-to-caption and speech-end-to-playback averages, p50, and p95. It also shows capture state, input level, submitted phrase count, processing state and errors, dropped phrases/samples, and queue depths. The panel keeps at most 30 recent phrase records in browser memory and has a Reset action. It does not store diagnostics in the database. Playback statistics include only phrases for which browser speech emitted `onstart` or generated WAV playback emitted `onplaying`. A missing voice, skipped playback, or absent event leaves audible latency unavailable.

Captured phrase duration comes from audio sample count. Capture start, estimated speech onset/end, WAV encoding, binary send, caption arrival, playback queueing, and playback start use the browser's monotonic clock. Speech end is estimated by subtracting VAD trailing silence from the browser timestamp; audio delivery and scheduling add uncertainty. Speech-end-to-caption includes finalization, encoding, any client queue wait, network, and server processing. WebSocket round trip starts when the binary chunk is sent and ends when its result is received. Browser speech preparation is measured while selecting a voice and constructing the utterance. Playback queue wait ends when playback is requested; playback start delay ends at `onstart` or `onplaying`. Actual speaker output and browser synthesis internals cannot be measured by these APIs. A local phrase UUID and the server's per-connection `chunk_id` correlate a result with its timing record; neither is persisted as diagnostics by default.

The backend provides optional `transcription_time_ms` and `translation_time_ms` durations around its service calls; they include any wait for its provider concurrency slot. `processing_time_ms` is the broader server-side duration; optional Azure `preparation_time_ms` follows in `speech_audio`. Debug logs record only chunk IDs, audio byte counts, and stage/send durations, not audio, text, keys, or cookies. These durations use the backend's monotonic clock and are never subtracted from browser timestamps. Cached results can omit provider stage timings. Diagnostics are for local observation, not a performance guarantee. A p50 caption target under 2 seconds for short phrases is an engineering goal, not a measured result.

Open **Live Meeting** (`/meeting`). The former `/workspace#meeting` URL redirects there. Choose a supported source language or automatic detection and one of the ten target languages. **Start interpretation** requests a browser tab with audio and then connects; **Share browser tab with audio** lets you grant capture first and start later. In the browser prompt, choose the meeting tab and enable **Share tab audio**. The browser must grant capture explicitly; TalkBuddy cannot silently read another tab. The page sends complete mono 16 kHz PCM WAV files through the existing authenticated WebSocket and never sends video frames. Pause discards an unfinished phrase; Stop releases shared tracks, closes the socket, and stops local speech playback. Navigation away from `/meeting` also releases capture and playback.

The listener uses local energy-based voice activity detection with an adaptive bounded noise floor. Defaults: 120 ms onset, 250 ms pre-roll, at least 600 ms voiced audio, 700 ms ending silence, 150 ms trailing padding, and a 12-second maximum phrase. These values are bounded in `meetingAudio.ts` and can be tuned in code after real recordings are reviewed. Silence and very short bursts are ignored. A 12-second uninterrupted utterance without a safe pause is skipped to cap memory rather than translated mid-sentence. This is pause-based phrase segmentation, not linguistic sentence detection or true simultaneous interpretation. Constant or speech-like noise can still trigger it. Server transcription and translation are sequential; captions appear only after each phrase completes. When provider calls fall behind, the socket keeps three waiting phrases and drops newer ones, with a visible warning.

Completed translations are queued for browser `speechSynthesis` playback in result order, one utterance at a time. TalkBuddy selects an installed voice matching the chosen language tag; it never silently uses a voice from an unrelated language. The interface reports voice availability separately from text translation. If no matching voice is installed, a warning appears and translated captions continue without speech. Voice availability and quality depend on the browser and operating system. Speech plays **only on the local device** and is never injected into Google Meet or broadcast to other participants. **Mute original tab audio** uses the browser's optional `suppressLocalAudioPlayback` constraint; if unsupported, use the tab's own mute control. The activity meter samples the captured audio level at most ten times per second and falls to zero on pause or stop. Phrase timestamps indicate when the browser received a completed result, not when the speaker began. Use headphones to avoid acoustic feedback. The tab must remain open and active enough for browser capture and speech APIs; background throttling, permission revocation, and autoplay rules can interrupt operation.

Audio is processed by Groq and is not stored by TalkBuddy. Text history stays off unless enabled in Settings **and** checked in the listener. A saved listener session uses the same session and per-chunk request IDs as the microphone workspace. Reconnect attempts are limited to three with exponential backoff and jitter; capture pauses during reconnect. Stop cancels local capture and playback promptly without waiting for provider work. A phrase already sent can still finish server-side, but the browser does not replay it after reconnect. Exactly-once processing across network failures is not guaranteed; saved history requests have server-side idempotency. Do not use this mode to capture a meeting without the participants' permission. Test in a supported desktop browser over localhost or HTTPS with a consenting meeting tab; actual end-to-end latency and accuracy depend on provider and browser conditions and have not been benchmarked.

### Windows 11 and Chromium manual audio checklist

These checks require a real signed-in browser and a running backend; automated mocks do not verify them. Use headphones, a consenting meeting tab, and a short phrase. In Diagnostics, record actual caption p50/p95, playback p50/p95, STT, translation, optional Azure preparation, dropped samples, and queue depth only after observing them. Test with history saving off first.

1. On `/microphone`, speak English and check Hindi captions, then Hindi audio with a compatible installed browser voice.
2. Repeat English to Marathi captions and Marathi audio. If a voice is missing, confirm captions continue and the warning is visible.
3. On `/meeting`, share a browser tab with audio and check translated captions and local playback. Verify that closing tab sharing stops capture.
4. In both modes, test Pause, Resume, Stop during an in-flight translation, microphone unplugging, browser-tab closure, and temporary network disconnection. Confirm no stale audio plays after Stop and no phrase is replayed after reconnect.
5. Test a noisy room, background-tab behavior, and repeated phrases for 10 minutes. Record dropped phrases, dropped samples, provider errors, and queue depth. Compare caption and audible latency separately.
6. If Azure credentials are configured, explicitly choose Azure speech and repeat the audio checks. If not configured, confirm the browser shows the configuration error and Browser voice remains selectable.

None of these real-device scenarios have been verified by the automated suite. The 2-second p50 caption goal requires measurements on a real setup before it can be claimed.
