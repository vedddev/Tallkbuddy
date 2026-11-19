# TalkBuddy backend

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

Production requires `APP_ENV=production`, exact HTTPS `PUBLIC_ORIGIN`, matching `CORS_ORIGINS`, valid async PostgreSQL `DATABASE_URL`, and `GROQ_API_KEY`. Optional Azure speech needs both key and region. Production startup rejects unsafe values before serving. The frontend and proxied `/api` and `/ws` must share one public origin for the current cookie/CSRF design. Session tokens are opaque and stored only as hashes; no session-signing secret is used.

Run `python -m pytest -q` for backend tests. Review [the production readiness, migration, backup, recovery, and smoke-test guide](../docs/PRODUCTION_READINESS.md) before deployment. See [the WebSocket protocol](WEBSOCKET_PROTOCOL.md) for audio limits and authentication. TalkBuddy plays translated speech locally; it does not inject sound into a meeting application.

For a dedicated staging host and test-only account, [`scripts/staging_smoke.py`](scripts/staging_smoke.py) checks HTTPS HTTP/WSS authentication, Origin, CSRF, cookies, logout, and readiness without making a paid provider call. It requires explicit `STAGING_CONFIRM=1`; see the [Phase 14 validation instructions](../docs/PHASE14_VALIDATION.md). It is not a browser or audio test.
