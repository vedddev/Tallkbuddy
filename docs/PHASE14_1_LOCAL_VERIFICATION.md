# Phase 14.1 local audio verification — 2026-11-19

## Scope and evidence rules

This is a **local development** check, not a staging or production deployment. The existing `backend/.env` was inspected only through safe presence flags; no key or database password was printed. A generated development test account was registered and removed by exact ID/email after each local smoke run. History was not enabled. No raw microphone audio was recorded or persisted by the verification script.

The physical-browser steps below remain **NOT VERIFIED** until a person reports observations from a normal browser session. An HTTP response, mocked UI test, or synthetic audio cannot establish microphone capture or audible TTS.

## Environment and local services

| Check | Status | Observed evidence |
| --- | --- | --- |
| OS | NOT VERIFIED | User reports Windows 11; system OS query was denied, so the exact build was not independently confirmed. |
| Browser | PASS (installed only) | Chrome `157.0.8103.79` and Edge executables are present. This is not a successful interactive browser run. |
| Python environment | PASS | Backend virtual environment exists; Python `3.11.9`. |
| Node dependencies | PASS | `frontend/node_modules` exists; Node `24.15.0`, npm `11.12.1`. |
| PostgreSQL service | PASS | `postgresql-x64-18` was already running. It was not restarted. |
| Development configuration | PASS | `APP_ENV=development`; database and Groq key are configured; Azure TTS is unconfigured. No production setting was changed. |
| PostgreSQL readiness | PASS | `/api/health/ready` returned HTTP 200 locally. |
| Alembic | PASS | `alembic current`: `20261115_02 (head)`; `alembic check`: no new upgrade operations. No migration was applied. |
| Backend liveness | PASS | `http://127.0.0.1:8000/api/health` returned HTTP 200. Backend was already running. |
| Vite frontend and proxy | PASS (HTTP only) | `http://127.0.0.1:5173/`, `/microphone`, and `/meeting` returned HTML 200; proxied `/api/health` and `/api/health/ready` returned JSON 200. Vite was already running. |
| Interactive browser rendering | NOT VERIFIED | Headless Edge failed before returning DOM output; browser automation could not inspect the UI. |

The frontend uses same-origin `/api` and `/ws`; Vite proxies them to `http://127.0.0.1:8000`. The session cookie is HttpOnly. `Secure=false` is expected for local HTTP development; production requirements were not changed.

## Authentication, WebSocket, and provider results

The opt-in [`local_verification.py`](../backend/scripts/local_verification.py) was run against the local Vite origin. Its generated test accounts were cleaned up successfully.

| Check | Status | Evidence |
| --- | --- | --- |
| Registration and login | PASS (HTTP client) | Registration HTTP 201; login HTTP 200 with session and CSRF cookies. |
| Authenticated navigation/API | PASS (HTTP API only) | `/api/auth/me` returned 401 before login and 200 after login. Browser navigation remains unverified. |
| CSRF | PASS (HTTP client) | Logout without `X-CSRF-Token` returned 403. |
| Authenticated WebSocket | PASS (protocol client) | Connection through Vite `/ws/translate` accepted a valid start and returned `ready`. No audio was sent. |
| WebSocket Origin rejection | PASS (protocol client) | Untrusted Origin handshake was rejected with HTTP 403. |
| Logout and revocation | PASS (HTTP client) | Logout returned 200; reuse of the old session cookie returned 401. |
| Groq text translation to Hindi | PASS (live text path) | Authenticated `/api/ai/translate` returned 200, target `hi`, nonempty translated text with Devanagari characters. Meaning and speech were not independently judged. |
| Groq text translation to Marathi | PASS (live text path) | Authenticated `/api/ai/translate` returned 200, target `mr`, nonempty translated text with Devanagari characters. Meaning and speech were not independently judged. |
| Groq Whisper STT | NOT VERIFIED | No physical or other spoken WAV phrase reached the provider during this phase. |
| Azure WAV TTS | NOT VERIFIED | Azure credentials are absent. Browser speech synthesis still requires a matching installed voice and a real playback observation. |

The live text calls used the two user-specified English phrases. They prove only the REST LLM translation path; they do not prove VAD, WAV encoding, WebSocket audio results, browser captions, or audible playback.

## Real-device test matrix

| Test | Status | Evidence needed |
| --- | --- | --- |
| Chrome/Edge registration and login UI | NOT VERIFIED | Visible forms, authenticated navigation, and logout in a normal browser. |
| Microphone permission and selected device | NOT VERIFIED | Browser prompt and named physical input device. |
| Microphone input level and VAD phrase | NOT VERIFIED | Moving input indicator, incrementing phrase count, complete phrase result. |
| English → Hindi microphone captions | NOT VERIFIED | Real transcription and Hindi caption for the spoken test phrase. |
| English → Hindi audible local speech | NOT VERIFIED | Matching installed Hindi voice and audible playback. |
| English → Marathi microphone captions | NOT VERIFIED | Real transcription and Marathi caption for the spoken test phrase. |
| English → Marathi audible local speech | NOT VERIFIED | Matching installed Marathi voice and audible playback. |
| Meeting-tab capture to Hindi | NOT VERIFIED | User-authorized tab audio, speech detected, captions and local playback. |
| Meeting-tab capture to Marathi | NOT VERIFIED | Same checks with Marathi target. |
| Start/Pause/Resume/Stop and resource cleanup | NOT VERIFIED | Normal browser controls, track stop, and no stale audio. |
| Stop during processing, refresh, disconnect, expiry | NOT VERIFIED | Controlled real-browser recovery checks. |
| Permission denial and device disconnection | NOT VERIFIED | Browser error and cleanup observations. |

TalkBuddy plays translated speech **locally**. It does not send that speech to meeting participants.

## Latency

**Real-audio sample count: 0.** Speech-end to caption, speech-end to playback, STT, translation, TTS, and playback queue measurements are therefore **NOT VERIFIED**. No p50, p95, or average for the real-audio pipeline is reported. The two live **text** calls were not timed as a speech benchmark.

For each language pair, reset the Diagnostics panel, speak the requested phrase and additional short phrases, and download numeric timings. If fewer than 30 valid phrases are collected, record the count and available values without presenting a representative benchmark. Keep failures and dropped phrases separate. Speech-end timestamps are VAD estimates; browser and server monotonic clocks must never be subtracted from each other.

## Bugs and limitations found

- The first local smoke run returned registration HTTP 422 because its generated `example.invalid` email is rejected by the email validator. The **test harness**, not the product registration route, was corrected to use an accepted `example.com` test address; a regression test now validates generated addresses.
- Headless Edge returned no DOM and exited before UI inspection. Its errors include unavailable Windows credential encryption and a GPU process failure. This is an environment/browser-automation blocker, not evidence of an application defect. No security setting was weakened to work around it.
- Windows `System.Speech` could not create a synthetic WAV output in this environment (`SetOutputToWaveFile` raised a null-reference error). No synthetic WAV was submitted or treated as real microphone evidence.
- Browser voice availability, physical microphone permission, Groq Whisper handling of actual speech, and local audio playback remain unverified.

## Manual continuation in a normal browser

1. Open `http://127.0.0.1:5173` in Chrome and sign in. On `/microphone`, choose the physical microphone, select English source or automatic detection and Hindi target, and press Start. Grant permission. Speak **“Hello everyone, welcome to our meeting.”** Observe input level, phrase count, original and Hindi captions, voice warning/playback status, and audible Hindi. Open Diagnostics and record values or download timing CSV. Press Pause, Resume, then Stop; confirm the browser microphone indicator turns off.
2. Repeat with Marathi target and **“Today we are testing our real-time translation application.”** Confirm Marathi captions and audible Marathi using a matching browser voice. If no voice exists, record captions as observed and speech as unavailable rather than substituting another language.
3. On `/meeting`, share a separate tab containing spoken audio and enable **Share tab audio**. Repeat Hindi and Marathi. End sharing and confirm TalkBuddy stops capture. This is local playback only.
4. In separate controlled runs, deny permission, unplug the microphone, refresh, interrupt the network, log out, and Stop during processing. Record exact visible errors and cleanup behavior.

Report the browser version, OS version, microphone, installed Hindi/Marathi voices, observed caption text, playback audibility, Diagnostics values, and errors. Avoid sharing cookies, passwords, API keys, or private meeting speech. If those observations are provided, update the matrix above with evidence; do not infer success from the HTTP and text checks.

## Automated regression checks

Observed after the harness fix: backend `pytest` **212 passed, 2 skipped** (dedicated PostgreSQL and opt-in live Groq tests), with one Starlette TestClient deprecation warning; frontend Vitest **104 passed**; TypeScript check and Vite production build **passed**. The live Groq text calls above were run separately through the local HTTP endpoint, not through the skipped pytest live marker.

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.local_verification --live
```

`--live` makes two billable Groq **text** calls and requires development mode plus a local PostgreSQL URL. Omit it for the non-provider auth/WebSocket smoke. The script does not record audio and deletes only its generated test account. Frontend regression checks remain `npm.cmd test`, `npm.cmd run typecheck`, and `npm.cmd run build` from `frontend/`.
