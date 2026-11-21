# Backend CI teardown timeout investigation

## Evidence and cause

The failed hosted run [44921835245](https://github.com/vedddev/Tallkbuddy/actions/runs/44921835245) ran backend pytest on Linux with Python 3.11.18. Its last completed test was `test_interim_disabled_by_default_never_calls_provider`; the 90-second timeout occurred in `auth_harness` while `TestClient.__exit__` waited for AnyIO's portal thread to join. A subsequent review-branch run [44924392838](https://github.com/vedddev/Tallkbuddy/actions/runs/44924392838) moved the timeout to the next interim-caption test after fixing that first test's close handshake.

Before changing application code, temporary, opt-in fixture diagnostics printed setup and teardown boundaries, pending task names, coroutine names, task stacks, cancellation state, and active WebSocket count. The diagnostic Linux run [44924719955](https://github.com/vedddev/Tallkbuddy/actions/runs/44924719955) identified the exact task: `AsyncAdapt_aiosqlite_connection._terminate_graceful_close` was still pending at fixture teardown and remained pending after cancellation for at least ten seconds. Active WebSocket connections were zero. In isolated Windows runs, the task appeared when an interim test sent `stop` and immediately exited its WebSocket context. Waiting for the server's close frame (code 1000) removed it. The test had left the server's request-scoped SQLite session to be cancelled by Starlette's test-session context manager; SQLAlchemy then had to clean up an unreturned connection during portal shutdown.

A separate cancellation regression was reproduced with a focused test: `_cancel_interim()` suppressed `CancelledError` raised when its **parent WebSocket task** was cancelled while awaiting a child task. That could obstruct cancellation during shutdown. The helper now ignores only the expected child cancellation and propagates parent cancellation.

## Changes

- Every WebSocket test that sends `stop` waits for the server close frame, so the server task and its database dependency finish before `TestClient` teardown.
- The isolated SQLite fixture now creates its schema and disposes its engine on the TestClient portal loop. That removes an additional cross-loop lifecycle risk, although loop alignment alone did not eliminate the stranded task while tests still skipped the close handshake.
- `_cancel_interim()` preserves parent cancellation while still awaiting and cancelling interim transcription.
- A regression test proves parent cancellation is propagated.
- Temporary task diagnostics are enabled only by `TALKBUDDY_TASK_DEBUG=1` in the review branch's CI run. They report task names and stack locations without private content. Remove the flag and fixture instrumentation after the final Linux verification.

Authentication, Origin checks, rate limits, final phrase processing, TTS ordering, and the interim-caption protocol are unchanged.

## Verification

- Windows, Python 3.11.9: `python -u -m pytest tests/test_websocket.py -q -s --timeout=90 --timeout-method=thread` with task diagnostics — **59 passed**, zero pending SQLite close tasks at fixture teardown.
- Windows, Python 3.11.9: `python -m pytest -q --timeout=90 --timeout-method=thread` — **255 passed, 2 skipped** on each of two consecutive runs. One existing Starlette `httpx` deprecation warning remains.
- Linux reproduction was attempted through WSL, but the installed `docker-desktop` distribution could not start (`HCS_E_SERVICE_NOT_AVAILABLE`); Docker and a separate Linux distribution were unavailable. No Linux run with the fix has been observed yet.
- The first two hosted review-branch runs still failed; one supplied the decisive task snapshot. A new run containing the close-handshake changes for all affected tests is required before treating CI as fixed.

To verify on Linux or GitHub Actions, run from `backend/`:

```bash
python -m pytest tests/test_websocket.py -vv --timeout=90 --timeout-method=thread
python -m pytest -vv --timeout=90 --timeout-method=thread
python -m pytest -vv --timeout=90 --timeout-method=thread
```

Check that `test_interim_disabled_by_default_never_calls_provider` and fixture teardown complete promptly, with no timeout or pending task warnings. The final acceptance criterion is a successful hosted backend job on a commit containing this fix.
