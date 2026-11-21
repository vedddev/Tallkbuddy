# Phase 15 — Audio reliability and CI diagnosis

## Confirmed findings

- GitHub Actions run `44721722388` installed dependencies and reached `python -m pytest -q`. It printed the 66% progress line at 10:44:33 UTC and was canceled at 12:35:14 UTC. Quiet pytest output does not identify which test among the remainder blocked. The exact blocking test and operation remain **NOT VERIFIED**. A local Windows run of the complete backend suite completed in about 30 seconds; it does not reproduce the Linux runner hang.
- The capture worklet previously allowed only one 20 ms audio block outstanding. If the main thread missed one acknowledgement, subsequent blocks were dropped. The worklet now holds at most eight pending blocks. On overflow it discards the backlog and reports the exact dropped sample count with the next delivered block. VAD resets after a gap so noncontiguous audio cannot become one phrase.
- The UI previously said a partial phrase was discarded whenever samples dropped, even during silence. It now counts a dropped phrase only if VAD was active.
- Browser speech synthesis previously reported `playing` when `speak()` was called. It now reports `playing` only after `onstart`; generated WAV playback already waits for `onplaying`.
- WebSocket queued phrases were cleared on disconnect without updating the dropped-phrase count. Unsent phrases are now counted. Potentially processed in-flight phrases remain unconfirmed and are never replayed.
- A queued worklet block was timestamped when the main thread processed it, making speech-end latency look shorter than it was. Blocks now carry their AudioContext capture time; the browser converts the elapsed AudioContext delay to its own monotonic clock before recording speech end. Browser and server clocks are still never subtracted from each other.

## CI follow-up

The backend CI job now runs verbose pytest with a 90-second per-test timeout and a 15-minute job limit. This preserves the full suite and should reveal the exact test and thread stacks on the next GitHub run. No production credentials or database are supplied to ordinary unit tests. The live Groq test remains explicitly opt-in. **Hosted CI passing is NOT VERIFIED until a new run succeeds.**

## Automated verification

| Check | Result |
| --- | --- |
| Backend pytest with per-test timeout | 216 passed, 2 skipped, 1 Starlette deprecation warning |
| Backend pytest in a tracked-file copy without `.env`, Groq key, or database URL | 216 passed, 2 skipped, 1 warning |
| Frontend Vitest | 109 passed |
| Frontend TypeScript and production build | Passed |
| Desktop bridge pytest using its own virtual environment | 51 passed |
| Python dependency check and `git diff --check` | Passed |

The tests use synthetic or mocked audio and providers. They do not measure real latency or establish Hindi/Marathi voice availability on a user device.

## Latency and resource limits

The existing diagnostics panel measures browser speech-end-to-caption and speech-end-to-playback start, WAV encoding, WebSocket round trip, server STT/translation, optional Azure TTS preparation, and playback queue/start delay. It stores at most 30 phrase records in memory. The worklet queue is bounded to eight blocks (about 160 ms at its 20 ms block size), the socket queue to three waiting phrases, and each speech playback queue to eight items. A phrase that overflows any queue is reported; no audio is persisted by these diagnostics. These are implementation limits, **not measured latency improvements**. No real-device p50 or p95 was collected in this phase.

## Real-browser checklist — NOT VERIFIED

Use Windows 11 with current Chrome or Edge, local HTTPS or localhost, a signed-in test account, and headphones. Open Diagnostics and reset it before each run. Do not use a production account or record private meeting audio.

1. Open `/meeting`, press **Share browser tab with audio**, select a separate YouTube tab with spoken English, and enable **Share tab audio**. Confirm input activity moves. Stop if the browser does not provide an audio track.
2. Select English or Auto detect as source and Hindi as target. Start interpretation. Confirm complete English phrases and Hindi captions. Confirm a matching Hindi browser voice starts playback, or a clear captions-only warning appears. Record dropped samples, dropped phrases, caption p50/p95, and playback p50/p95 from Diagnostics.
3. Stop, reset Diagnostics, and repeat with Marathi. Verify a Marathi voice or captions-only warning independently of Hindi.
4. Repeat while the main thread is busy; confirm the overflow warning and counts correspond to a real gap. Check that no partial phrase is translated after overflow.
5. Interrupt the network during speech. Confirm capture pauses, queued phrases are counted as dropped, reconnection is bounded, and old phrases are not replayed. Resume with a new phrase.
6. Exercise Pause, Resume, Stop, tab-share termination, browser refresh, and navigation away. Confirm tracks and speech playback stop. Verify no stale caption or playback appears after Stop.
7. Repeat the same Hindi and Marathi checks on `/microphone` with a physical input. Test permission denial and device removal.

Record browser and OS versions, device, phrase count, actual latency values, and errors in a separate local test record. Automated tests and synthetic audio do not establish real browser or provider performance.

## Remaining limitations

- The canceled CI log does not identify the hanging test. The next verbose, timeout-bounded run is required to establish and fix that root cause.
- AudioWorklet and browser speech behavior still need physical browser verification. A sustained main-thread stall longer than the bounded queue can still lose audio.
- The client does not replay ambiguous in-flight phrases after reconnect, so it avoids duplicate playback but cannot guarantee delivery without server-side acknowledgement and idempotency.
- Browser voices, Azure credentials, network conditions, and real speaker output were not verified here.
