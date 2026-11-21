# TalkBuddy backend

Experimental interim captions are disabled by default. Set `WS_INTERIM_ENABLED=true` only for a controlled local test after reviewing Groq usage; each accepted preview is an additional Whisper request. The browser also requires `VITE_INTERIM_CAPTIONS_ENABLED=true` and user opt-in. `WS_INTERIM_MIN_INTERVAL_SECONDS`, `WS_INTERIM_MAX_REQUESTS`, `WS_INTERIM_MAX_AUDIO_BYTES`, and `WS_INTERIM_TIMEOUT_SECONDS` bound the preview path. Finalized translation, history, and TTS continue through the existing protocol. See [WebSocket protocol](WEBSOCKET_PROTOCOL.md#experimental-interim-captions-phase-19).

Use Python 3.11+, PostgreSQL, and the repository's `shared/languages.json`. From `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --ws websockets --ws-max-size 1048576 --ws-max-queue 4
```

Fill `.env` privately before migrations. `alembic current` must connect successfully; create the PostgreSQL role/database yourself. Never commit `.env`. Development permits the local Vite proxy origins. `GET /api/health` is liveness; `/api/health/ready` and `/api/health/db` check PostgreSQL. Normal tests use mocks and SQLite; the optional integration test needs a separate `TEST_DATABASE_URL` whose database name contains `test`.

Production requires `APP_ENV=production`, exact HTTPS `PUBLIC_ORIGIN`, matching `CORS_ORIGINS`, valid async PostgreSQL `DATABASE_URL`, and `GROQ_API_KEY`. Optional Azure speech requires a private key, region, HTTPS Azure resource endpoint, and explicit `AZURE_TTS_ENABLED=true`; it is disabled by default. Voice names are checked against Azure's live catalog before synthesis. Enabling it can incur provider charges. Production startup rejects unsafe values before serving. The frontend and proxied `/api` and `/ws` must share one public origin for the current cookie/CSRF design. Session tokens are opaque and stored only as hashes; no session-signing secret is used.

Run `python -m pytest -q` for backend tests. Review [the production readiness, migration, backup, recovery, and smoke-test guide](../docs/PRODUCTION_READINESS.md) before deployment. See [the WebSocket protocol](WEBSOCKET_PROTOCOL.md) for audio limits and authentication. TalkBuddy plays translated speech locally; it does not inject sound into a meeting application.

For a dedicated staging host and test-only account, [`scripts/staging_smoke.py`](scripts/staging_smoke.py) checks HTTPS HTTP/WSS authentication, Origin, CSRF, cookies, logout, and readiness without making a paid provider call. It requires explicit `STAGING_CONFIRM=1`; see the [Phase 14 validation instructions](../docs/PHASE14_VALIDATION.md). It is not a browser or audio test.

For a separate, manually invoked live Groq check, run `python -m scripts.check_groq_live --live` from `backend/` after configuring the private `GROQ_API_KEY`. The flag explicitly permits one billable translation request; without it, the script exits before loading credentials. It is outside pytest discovery. Routine pytest never needs a real Groq key; the opt-in `tests/test_live_groq.py` also skips unless `RUN_LIVE_GROQ_TESTS=1`.
