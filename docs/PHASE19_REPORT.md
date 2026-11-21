# Phase 19: Provisional live captions

## Architecture

The existing AudioWorklet and pause-based VAD remain authoritative for finalized phrases. While VAD holds an active phrase, an optional callback takes at most four cumulative snapshots, nominally 1.8 seconds apart, encodes each as a complete 16 kHz mono PCM16 WAV, and submits it over the authenticated `/ws/translate` connection. These are periodic Groq Whisper transcriptions, **not native streaming STT**. The final WAV still follows the existing sequential transcription → translation → optional TTS path.

The new protocol uses `start.interim_captions`, an optional capability in `ready`, `interim_audio` JSON followed by binary WAV, `interim_caption` or `interim_error`, and optional `interim_cancel`. Each preview has a phrase UUID and increasing revision. The frontend replaces older revisions for that phrase, ignores stale and post-final responses, and removes provisional text on final result, error, pause, stop, capture overflow, or disconnect. The server runs at most one preview task per connection and cancels it before processing a final WAV. It rechecks the authenticated database session before sending a preview. Existing session cookies, Origin checks, and final WebSocket messages are unchanged.

Interim text is displayed only in the original caption panel. It is never translated, synthesized, saved to history, or included in TXT/SRT/PDF export. The final phrase remains authoritative. No interim audio is stored.

## Flags, limits, and cost

Both flags default to **false**: backend `WS_INTERIM_ENABLED` and frontend `VITE_INTERIM_CAPTIONS_ENABLED`. When both are enabled, the user must additionally check **Experimental interim captions** before starting a session. An old or disabled server advertises `interim_captions:false`, and the browser continues with final captions only.

Defaults: 1.8-second browser snapshot interval (bounded 1.5–5 seconds), four successful snapshots per phrase, 256,000 bytes per snapshot, 0.5–8 seconds of 16 kHz mono PCM16 WAV, 1.5-second minimum server interval, 50 accepted interim calls per connection, one in-flight preview, and an 8-second provider timeout. The existing provider semaphore and queue timeout still apply. Rejected previews degrade to final captions. Limits are per connection/process, not a distributed billing quota.

Each accepted snapshot is an **additional billable Groq Whisper call**. A phrase can generate up to four extra calls, and cumulative snapshots repeat earlier speech, bounded by the caps above. Leave the feature off until real audio quality, latency, call volume, and costs are reviewed. No new provider was added.

## Files modified

- Backend: `app/core/config.py`, `app/ws/audio.py`, `app/ws/protocol.py`, `app/ws/translate.py`, `tests/test_websocket.py`, `.env.example`, `README.md`, `WEBSOCKET_PROTOCOL.md`.
- Frontend: `src/lib/meetingAudio.ts`, `src/lib/socket.ts`, `src/lib/types.ts`, `src/components/MeetingInterpreter.tsx`, three focused test files, `.env.example`, `README.md`.
- This report: `docs/PHASE19_REPORT.md`.

## Automated verification

| Check | Result |
| --- | --- |
| Backend pytest | 254 passed, 2 skipped; one pre-existing Starlette/httpx deprecation warning |
| Frontend Vitest | 125 passed |
| TypeScript | Passed |
| Frontend production build | Passed |
| Desktop bridge pytest | 51 passed |

Backend pytest used a process-local `WS_IDLE_TIMEOUT_SECONDS=60` override because the existing local `backend/.env` contains an invalid value (`60-`). The `.env` file and production validation were not changed. Tests mock provider and browser audio; no paid API requests were made.

The Phase 19 `ready` field is serialized only when interim captions were explicitly requested. A targeted regression test checks that legacy `ready` still includes `source_language:null` and omits `interim_captions`, while requested-but-disabled and enabled states return `false` and `true` respectively. `tests/test_websocket.py -vv` passed all 58 tests after this check was added.

## Manual browser verification

**NOT VERIFIED.** On a development machine with approved Groq usage, set both flags to true, restart services, sign in, and opt in on `/microphone` or `/meeting`. With a real microphone or permitted shared-tab speech, speak for more than two seconds, watch the Interim label update without adding duplicate rows, then pause and confirm the final caption replaces it. Repeat with English, Hindi, and Marathi; test explicit source hints and Auto-detect. Confirm translated speech starts only after final results and saved history/export contain no provisional text. Test Pause, Stop, tab closure, disconnect, a slow provider response, and a ten-minute session. Record actual request counts, errors, p50/p95 interim-to-final latency, and Groq usage. Do not infer performance from mocked tests.

## Limitations and Phase 20 readiness

- Interim wording may change or be inaccurate because Whisper transcribes incomplete, cumulative speech snapshots. No word timestamps or confidence scores are claimed.
- A slow or rate-limited provider may yield no preview; finalized captions continue. The browser sends best-effort previews without replay, and the backend limit is per connection rather than a global cost quota.
- Snapshot encoding runs on the browser main thread only when the experimental feature is enabled. Real-device profiling is needed before production rollout.
- The feature is **implemented and automated-tested**, but **not ready for production enablement** until real audio, latency, accuracy, and billing are verified. Phase 20 has not been started.
