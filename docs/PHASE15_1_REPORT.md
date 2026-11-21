# Phase 15.1 — CI and real-audio verification

## CI investigation

**Status: NOT VERIFIED on GitHub.** The local workflow file runs backend pytest from `backend/` with `-vv`, a 90-second per-test timeout using `pytest-timeout`, and a 15-minute backend job limit. It does not supply real Groq or database credentials. These workflow edits remain local in the working tree. The latest accessible runs (`44721722388` and `44719253979`) target earlier commits and do not establish a result for these changes. The previous quiet run reached 66% and was canceled; its output cannot identify the blocking test. A new hosted run is required to name the test and inspect any timeout stack trace.

Audit findings:

- `tests/test_live_groq.py` skips unless `RUN_LIVE_GROQ_TESTS=1`; it also skips without a Groq key. `tests/test_postgres_integration.py` skips without an explicit, dedicated `TEST_DATABASE_URL`. Neither performs an import-time connection.
- Provider unit tests use mocks and `httpx.MockTransport`. The staging smoke tests replace the HTTP client and require explicit opt-in. The offline migration subprocess is the slowest local backend test (3.58 seconds), but completes before the 66% point; this does not prove the Linux stall location.
- WebSocket tests contain blocking `receive_json()` calls and app tests use `TestClient` lifespan cleanup. These remain plausible Linux-only wait locations, but no hosted verbose log identifies one. The per-test timeout will bound them without skipping coverage. Do not change their behavior on speculation.
- A tracked-file copy with no `.env`, `GROQ_API_KEY`, `DATABASE_URL`, `TEST_DATABASE_URL`, or live-test flag, and with `CI=true`, passed the ordinary backend suite: **216 passed, 2 skipped** in 47.12 seconds. No live provider or database request was needed.

## Browser audio verification

**Real browser and audio: NOT VERIFIED.** No browser-control tool with permission access was available, and the user could not perform the physical test during this phase. Automated AudioWorklet, WebSocket, and playback tests use synthetic audio or mocks; they are not evidence of real YouTube capture or audible Hindi/Marathi speech.

Manual procedure for Chrome or Edge on Windows 11:

1. Start the documented local backend and Vite frontend, sign in, and open `/meeting`. Use headphones. Open a separate YouTube tab with spoken English; do not save or redistribute captured audio.
2. Choose English or Auto detect as source and Hindi as target. Select **Share browser tab with audio**, choose the YouTube tab, and enable **Share tab audio**. Press **Start interpretation**. Record whether input activity, original captions, Hindi captions, and audible Hindi playback occur. If no Hindi voice exists, record the captions-only warning.
3. Open Diagnostics, reset it, and collect at least 30 valid phrases if practical. Record the valid-phrase count, caption average/p50/p95, playback average/p50/p95, STT/translation durations, captured and accepted phrase counts, dropped phrases/samples, buffer overflows, disconnects, and playback failures. Do not report a percentile as representative for a small sample.
4. Stop, switch target to Marathi, and repeat. Verify Marathi voice availability separately from Hindi.
5. Pause and resume; stop during processing; close the shared tab; interrupt and restore the network. Confirm no stale audio plays, no submitted phrase is replayed after reconnect, and tracks stop on Stop or navigation.
6. To exercise buffer overflow, create sustained main-thread load while audio is captured. Confirm overflow and dropped-sample counters advance and incomplete speech is discarded. Avoid treating a synthetic unit test as this result.

Record browser version, OS, audio source, timestamps, errors, and diagnostics export. TalkBuddy plays translations locally; it does not broadcast into the YouTube tab or a meeting app.

## Reliability metrics

The collapsible Diagnostics panel now exposes **captured phrases**, **accepted phrases**, **dropped phrases**, **dropped samples**, **worklet buffer-overflow events**, **WebSocket disconnects**, and **playback failures**. Reset works even when there are only failures and no completed timing records. The existing bounded 30-record collection shows speech-end-to-caption and speech-end-to-playback latency, averages, p50/p95, and separate server STT/translation times. Playback latency remains unavailable until a browser `onstart` or WAV `onplaying` event occurs. Counters are in memory only and reset at session start or on request.

**Measured real-audio latency: NOT VERIFIED.** No p50, p95, or playback timing from a physical browser session was collected. The local backend test duration is a test runtime, not translation latency.

## Files changed in Phase 15.1

- `frontend/src/lib/audio.ts`, `frontend/src/lib/meetingAudio.ts`: carry an explicit worklet overflow-event count with dropped samples.
- `frontend/src/components/MeetingInterpreter.tsx`, `frontend/src/components/LatencyDiagnostics.tsx`: count and display capture, disconnect, overflow, and playback events.
- `frontend/src/test/audio.test.ts`, `frontend/src/test/latency.test.tsx`, `frontend/src/test/meetingInterpreter.test.tsx`: regression coverage for the new counters and reset behavior.
- `frontend/README.md`: correct the documented worklet buffer and diagnostics counters.
- `docs/PHASE15_1_REPORT.md`: investigation, manual verification, and release decision.

The Phase 15 workflow, timeout dependency, audio reliability fixes, and `docs/PHASE15_REPORT.md` were already present in the local workspace when Phase 15.1 began. No backend API, authentication, CSRF, Origin, database migration, or provider configuration was changed in Phase 15.1.

## Regression results

| Check | Result |
| --- | --- |
| Backend pytest in credential-free tracked-file copy with `CI=true` | 216 passed, 2 skipped; 1 Starlette deprecation warning |
| Frontend Vitest | 110 passed |
| Frontend TypeScript | Passed |
| Frontend production build | Passed |
| Desktop bridge pytest in its own virtual environment | 51 passed |

## Remaining issues and Phase 16 decision

**NOT READY for Phase 16 release work.** The exact GitHub Linux blocking test is still unknown; the verbose, timeout-bounded workflow needs a hosted run. Real microphone and YouTube-tab Hindi/Marathi captions, voice playback, reconnect behavior, cleanup, and latency remain NOT VERIFIED. Browser voice availability and optional Azure TTS also require target-environment checks. Existing tests establish code behavior under mocks, not end-to-end audio reliability.
