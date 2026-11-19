# TalkBuddy production readiness (Phase 13)

This is a deployment plan, not evidence of a deployed or production-ready service. Browser audio is translated and played **locally**. TalkBuddy does not broadcast into Google Meet or Zoom. The desktop bridge and VB-CABLE remain optional experimental tools.

## Audit and priorities

| Severity | Finding | Status |
| --- | --- | --- |
| Critical | Production could start without PostgreSQL, Groq credentials, or a trusted public origin. | Fixed: startup rejects missing/unsafe production configuration. |
| High | Origin trust could be derived from an attacker-controlled Host header. | Fixed: production HTTP writes and WebSockets use `PUBLIC_ORIGIN`. |
| High | Separate frontend/API sites cannot use the current readable CSRF cookie reliably. | Deployment constraint: serve frontend, `/api`, and `/ws` from one public HTTPS origin. Cross-site deployment requires a separately designed auth/CSRF flow. |
| Medium | Login limits, provider slots, WebSocket limits, and operational counters are in memory. | Documented: enforcement is per process. One backend process is the supported initial deployment topology; shared limits are required before horizontal scaling. |
| Medium | Provider requests and long WebSockets can consume resources. | Existing audio/control limits, timeouts, bounded provider slots and frontend queues retained; proxy body/frame limits and capacity monitoring required. |
| Medium | Managed database backup, restore, TLS, and real browser/provider behavior are unverified here. | Release gates below; verify in target environment. |
| Low | No external metrics sink is configured. | Fixed-field JSON logs and internal bounded counters added; connect a private log/metrics collector before launch. |

Existing controls retained: Argon2id passwords; opaque random session tokens hashed at rest; HttpOnly session cookies; Secure cookies in production; SameSite=Lax; session expiration and server-side revocation; CSRF checks; exact WebSocket Origin checks; ownership-scoped history; explicit history opt-in; no raw-audio persistence.

## Production topology and configuration

Use a persistent ASGI service with WebSocket support, managed PostgreSQL, and one public HTTPS origin. Serve the static `frontend/dist` and reverse-proxy `/api` and `/ws` to the backend on that origin. A static host such as Vercel is suitable only if its routing can proxy both paths to the persistent backend while preserving this same origin. A serverless function is not a substitute for the WebSocket backend. Terminate TLS at the trusted proxy; expose WSS through the same host. Restrict backend network access to the proxy and database.

Set these backend variables privately: `APP_ENV=production`, `PUBLIC_ORIGIN=https://your-domain.example`, `CORS_ORIGINS=["https://your-domain.example"]`, `DATABASE_URL` (managed `postgresql+asyncpg` URL), and `GROQ_API_KEY`. Do not set `AUTH_COOKIE_SECURE=false`. Set `AZURE_SPEECH_KEY` **and** `AZURE_SPEECH_REGION` only when Azure speech is used; otherwise leave both empty. Set `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, provider concurrency, timeouts, and rate limits for the target service capacity. Never commit secrets or put them in `VITE_` variables. Session tokens are random database-backed values; this architecture has no separate session-signing secret.

For the frontend build, leave `VITE_API_BASE_URL` unset so `/api` and `/ws` use the page origin. `VITE_BACKEND_URL` is used only by the Vite development proxy. Ensure `shared/languages.json` is deployed alongside the backend, at the repository-relative path expected by `app.ai.languages`.

Start with one backend process. `uvicorn` must receive proxy headers only from the known proxy IP (`--proxy-headers --forwarded-allow-ips PROXY_IP`), not from arbitrary internet clients. Configure the proxy with an upload body cap at or above the configured 10 MiB REST audio limit, but no broader than needed; the WebSocket frame cap is `WS_MAX_AUDIO_BYTES` (default 1 MiB), and the Uvicorn `--ws-max-size` should match. Keep `--ws-max-queue 4`; use proxy WebSocket upgrade headers and read timeout above the backend idle/processing window. Do not rely on arbitrary forwarded IP headers for rate limits.

Example process command, from `backend/`, after setting private environment variables:

```sh
python -m alembic current
python -m alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws websockets --ws-max-size 1048576 --ws-max-queue 4 --proxy-headers --forwarded-allow-ips PROXY_IP
```

Bind to the private interface appropriate to your host; replace `PROXY_IP` with the actual trusted proxy address. Never run `--reload` in production. The proxy should answer HTTPS requests for the frontend and forward `/api` and `/ws` to this persistent process. [An Nginx example](nginx.conf.example) shows the required routing; replace every host, path, and certificate placeholder, then validate the proxy configuration before use. Configure its body and connection limits, TLS certificates, WebSocket upgrade, and idle timeout. No automatic deployment is configured.

## Health, logs, and monitoring

- `GET /api/health` is liveness; it does not call PostgreSQL or paid AI services.
- `GET /api/health/ready` is readiness; it runs `SELECT 1` against PostgreSQL. HTTP 503 indicates not ready.
- `GET /api/health/db` remains compatible with existing database checks.
- Health responses contain no credentials or SQL details. Provider availability requires separate controlled smoke testing; health endpoints never make paid calls.
- Backend emits fixed-field JSON logs with request ID, WebSocket ID, chunk ID, route/operation, status, duration, safe provider/error category, and queue depth where available. No raw audio, transcript, translation, cookie, or API key is intentionally logged. Treat logs as sensitive operational data and restrict access.
- In-process counters include HTTP requests/errors, active WebSockets, provider errors/timeouts, queue overflows, and connection rejections. Fixed-bucket duration histograms cover HTTP, STT, translation, and TTS. They are **not publicly exposed** and reset on process restart. Use a private collector before relying on them for alerting. Alert on readiness failures, sustained 5xx/429 rates, provider timeouts, queue overflow, and database pool exhaustion.

## Database changes, backup, and recovery

Use a dedicated managed PostgreSQL role with only the required schema permissions. Check `python -m alembic current` and review `python -m alembic upgrade head --sql` before applying migrations. Take a verified backup or snapshot first, schedule migrations during a controlled maintenance window, apply once, and then check `/api/health/ready`. Do not run destructive tests or migrations against production.

Example logical backup and restore commands, with passwords supplied via a secure prompt/secret manager (never in command history):

```sh
pg_dump --format=custom --no-owner --file=talkbuddy.backup --dbname=PRODUCTION_POSTGRES_URL
pg_restore --list talkbuddy.backup
pg_restore --clean --if-exists --no-owner --dbname=DISPOSABLE_RESTORE_TEST_URL talkbuddy.backup
```

Test restoration into a disposable database; never use the restore command against the live database without a specific recovery plan. Set retention and encryption on managed backups. Roll back application code by deploying the previous artifact; Alembic downgrades may lose data or fail after writes, so do not assume schema rollback is safe. For a failed schema change, restore a tested backup or prepare a forward repair. After a database outage, readiness returns 503; the SQLAlchemy pool uses pre-ping and should reconnect when PostgreSQL is available, but verify recovery in staging.

## Repeatable smoke test

In a staging environment with test-only users, real credentials, HTTPS, a Chromium browser, and a physical audio device:

1. Load the frontend and check `GET /api/health` (200), `/api/health/ready` (200), and `/api/health/db` (200). Confirm certificates and WSS.
2. Register and log in; confirm `GET /api/auth/me` succeeds with the cookie. Confirm missing CSRF is rejected on a protected write.
3. Open `/microphone`; grant permission, speak a short English phrase, and verify Hindi captions and local playback. Repeat for Marathi.
4. Open `/meeting`; explicitly share a tab **with audio**, verify incoming captions and local playback. Check permission denial and a missing audio track.
5. Confirm untrusted Origin requests/WebSocket handshakes are rejected; verify logout revokes the session and closes authenticated access.
6. Test Stop, device removal, network interruption, provider failure, 10-minute repeated phrases, and browser/tab closure. Record actual p50/p95 speech-end latency from diagnostics. Check logs for safe categories only.

Automated tests and mocked audio cannot establish any of these real-device outcomes. Never use production speech or user accounts for smoke tests.

## Release gates

| Gate | State | Evidence needed |
| --- | --- | --- |
| Configuration rejects unsafe production settings | PASS | Automated production settings tests |
| Existing backend/frontend/desktop regression suites | NOT VERIFIED | Record CI and local results for release artifact |
| HTTPS/WSS on deployed origin | NOT VERIFIED | Browser network inspection |
| Real microphone English-to-Hindi captions and speech | NOT VERIFIED | Staging device test |
| Real microphone English-to-Marathi captions and speech | NOT VERIFIED | Staging device test |
| Real meeting-tab captions and speech | NOT VERIFIED | Staging permission/device test |
| Permission denial and Stop cleanup | NOT VERIFIED | Browser inspection |
| 10-minute session and provider failure recovery | NOT VERIFIED | Staging test |
| p50/p95 latency measured | NOT VERIFIED | Real phrase diagnostics |
| Production database backup and restore tested | NOT VERIFIED | Disposable restore and checks |

Any NOT VERIFIED release gate remains a launch blocker until evidence is recorded. CI passing alone is insufficient.
