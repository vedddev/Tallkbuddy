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
- `/meeting` is the local meeting listener. `/history` and `/settings` retain their existing functions.
- `/workspace` remains the existing microphone translation workspace. Legacy `/workspace#translate` and `/workspace#meeting` URLs redirect to `/translate` and `/meeting` respectively. Leaving an active meeting route releases capture and speech playback.

History search and language filters apply to the currently loaded page of 20 sessions. The backend history API supports pagination but has no search or filter parameters, so the UI labels this scope explicitly.

## Manual frontend QA

Use browser responsive mode at 375, 768, 1280, and 1920 CSS pixels. Repeat in light and dark themes. Check the landing, login, register, overview, translate, meeting, history, settings, and legacy microphone workspace routes for horizontal scrolling, clipped controls, readable labels, and visible keyboard focus. For protected pages, sign in using a local development account.

- Submit login and registration with invalid and valid fields; use Tab, Shift+Tab, Enter, and the password visibility button. Confirm error and loading states.
- Open the mobile navigation drawer, cycle focus, close with Escape, and navigate to another route. Check that the theme preference survives reload.
- On Translate, enter long Hindi, Marathi, Japanese, Korean, and Chinese text; check wrapping, copy, speech, missing-voice errors, and a failed API request. The source selector is a label and swap aid; the text API detects source language itself.
- On History, test no results, a failed load, page changes, current-page search and filters, details, and deletion confirmation. Verify timestamps remain visible on mobile.
- On Live Meeting, verify Start, Pause, Resume, and Stop at mobile width, tab permission rejection, missing audio track, disconnect, captions, voice warning, and cleanup after navigation. Local playback does not broadcast into Google Meet.

Automated frontend tests cover core behavior, but browser capture, installed voices, provider responses, and exact visual layout require this manual check on the target browser and device.

## How translation works

The microphone workspace records mono samples with `AudioWorklet`, resamples to 16 kHz, and encodes each 1.25-second segment as a complete PCM WAV file. The socket sends one chunk at a time and keeps at most three waiting chunks in arrival order; new chunks are dropped if the provider falls behind. Stopping flushes the final microphone segment if it is at least 0.25 seconds. Disconnects stop microphone tracks and show a reconnect action. Reconnecting starts a new saved session when history is enabled.

History requires enabling `save_history_enabled` in Settings **and** checking “Save this conversation” in the workspace. The frontend creates and ends the backend translation session, sends a UUID `request_id` before each saved WAV chunk, and keeps unsaved results only in page memory. Text translation uses the existing REST endpoint and an `Idempotency-Key` when saving. Browser playback uses `speechSynthesis`; available voices vary by device. Raw audio is never saved by the frontend.

Microphone recording requires a secure context (`localhost` or HTTPS) and a browser with `AudioWorklet`. WebSocket results are chunk-based and may arrive with provider latency; this is not continuous streaming. If a user navigates away during an in-flight chunk, the socket closes and that incomplete chunk may not produce a result.

## Local meeting listener

Open **Live Meeting** (`/meeting`). The former `/workspace#meeting` URL redirects there. Choose a supported source language or automatic detection and one of the ten target languages. **Start interpretation** requests a browser tab with audio and then connects; **Share browser tab with audio** lets you grant capture first and start later. In the browser prompt, choose the meeting tab and enable **Share tab audio**. The browser must grant capture explicitly; TalkBuddy cannot silently read another tab. The page sends complete mono 16 kHz PCM WAV files through the existing authenticated WebSocket and never sends video frames. Pause discards an unfinished phrase; Stop releases shared tracks, closes the socket, and stops local speech playback. Navigation away from `/meeting` also releases capture and playback.

The listener uses local energy-based voice activity detection. It waits for speech of at least about 0.6 seconds and a pause of about 0.7 seconds before sending a phrase. Silence and very short bursts are ignored. A 12-second uninterrupted utterance without a safe pause is skipped to cap memory rather than translated mid-sentence. This is pause-based phrase segmentation, not linguistic sentence detection or true simultaneous interpretation. Server transcription and translation are sequential; captions appear only after each phrase completes. When provider calls fall behind, the socket keeps three waiting phrases and drops newer ones, with a visible warning.

Completed translations are queued for browser `speechSynthesis` playback in result order, one utterance at a time. TalkBuddy selects an installed voice matching the chosen language tag; it never silently uses a voice from an unrelated language. The interface reports voice availability separately from text translation. If no matching voice is installed, a warning appears and translated captions continue without speech. Voice availability and quality depend on the browser and operating system. Speech plays **only on the local device** and is never injected into Google Meet or broadcast to other participants. **Mute original tab audio** uses the browser's optional `suppressLocalAudioPlayback` constraint; if unsupported, use the tab's own mute control. The activity meter samples the captured audio level at most ten times per second and falls to zero on pause or stop. Phrase timestamps indicate when the browser received a completed result, not when the speaker began. Use headphones to avoid acoustic feedback. The tab must remain open and active enough for browser capture and speech APIs; background throttling, permission revocation, and autoplay rules can interrupt operation.

Audio is processed by Groq and is not stored by TalkBuddy. Text history stays off unless enabled in Settings **and** checked in the listener. A saved listener session uses the same session and per-chunk request IDs as the microphone workspace. Reconnect attempts are limited to three with backoff; the capture pauses during reconnect and stops if all attempts fail. Do not use this mode to capture a meeting without the participants' permission. Test in a supported desktop browser over localhost or HTTPS with a consenting meeting tab; actual end-to-end latency and accuracy depend on provider and browser conditions and have not been benchmarked.
