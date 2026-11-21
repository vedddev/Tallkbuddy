# Backend CI teardown timeout investigation

## Evidence and cause

The failed hosted run [44921835245](https://github.com/vedddev/Tallkbuddy/actions/runs/44921835245) ran backend pytest on Linux with Python 3.11.18. Its last completed test was `test_interim_disabled_by_default_never_calls_provider`; the 90-second timeout occurred in `auth_harness` while `TestClient.__exit__` waited for AnyIO's portal thread to join. The traceback places the portal in `asyncio.Runner.close()` / `_cancel_all_tasks()`, rather than in a test assertion.

Before changing application code, temporary, opt-in fixture diagnostics printed setup and teardown boundaries, pending task names, coroutine names, task stacks, cancellation state, and active WebSocket count. In the isolated Windows reproduction, the test sent `stop` and exited its WebSocket context without consuming the server close frame. At fixture teardown, the snapshot showed an unfinished `AsyncAdapt_aiosqlite_connection._terminate_graceful_close` task. After the test waited for and asserted the normal WebSocket close frame (code 1000), the same snapshot showed no pending SQLite close task. The isolated test and the full suite completed locally. This makes the unacknowledged close/connection cleanup race the strongest explanation for the hosted timeout. The exact pending task on the Linux runner was not captured by the old hosted log, so Linux confirmation remains outstanding.

A separate cancellation regression was reproduced with a focused test: `_cancel_interim()` suppressed `CancelledError` raised when its **parent WebSocket task** was cancelled while awaiting a child task. That could obstruct cancellation during shutdown. The helper now ignores only the expected child cancellation and propagates parent cancellation.

## Changes

- The interim-disabled WebSocket test waits for the server close frame after `stop`, so its request-scoped database session finishes before the fixture tears down `TestClient`.
- `_cancel_interim()` preserves parent cancellation while still awaiting and cancelling interim transcription.
- A regression test proves parent cancellation is propagated.
- Temporary diagnostic instrumentation was removed after collecting the task snapshot. No production logging of private content was added.

Authentication, Origin checks, rate limits, final phrase processing, TTS ordering, and the interim-caption protocol are unchanged.

## Verification

- Windows, Python 3.11.9: `python -u -m pytest tests/test_websocket.py -vv --timeout=90 --timeout-method=thread` — **59 passed**.
- Windows, Python 3.11.9: `python -m pytest -q --timeout=90 --timeout-method=thread` — **255 passed, 2 skipped** on each of two consecutive runs. One existing Starlette `httpx` deprecation warning remains.
- Linux reproduction was attempted through WSL, but the installed `docker-desktop` distribution could not start (`HCS_E_SERVICE_NOT_AVAILABLE`); Docker and a separate Linux distribution were unavailable. No Linux run with the fix has been observed yet.
- The existing hosted failure predates these changes. A new GitHub Actions backend run is required before treating CI as fixed.

To verify on Linux or GitHub Actions, run from `backend/`:

```bash
python -m pytest tests/test_websocket.py -vv --timeout=90 --timeout-method=thread
python -m pytest -vv --timeout=90 --timeout-method=thread
python -m pytest -vv --timeout=90 --timeout-method=thread
```

Check that `test_interim_disabled_by_default_never_calls_provider` and fixture teardown complete promptly, with no timeout or pending task warnings. The final acceptance criterion is a successful hosted backend job on a commit containing this fix.
