# Phase 14 staging validation record

**Decision: NOT READY.** No staging host, TLS certificate, dedicated staging database, test account, or browser/audio run has been supplied or verified in this workspace. Local `backend/.env` is configured for **development**, and there is no `TEST_DATABASE_URL`; it is not a staging configuration. Do not use development or production user data for this plan. This document records evidence only when a check has actually run.

TalkBuddy provides local translated captions and speech. It does **not** inject audio into Google Meet or Zoom. VB-CABLE and the desktop bridge are optional and are not required for staging browser tests.

## Staging architecture and blockers

Required layout, all under one real staging HTTPS host:

| Public path | Service |
| --- | --- |
| `/` | Static `frontend/dist` with SPA fallback |
| `/api/` | Persistent FastAPI process over a private proxy connection |
| `/ws/` | FastAPI WebSocket upgrade over a private proxy connection |

Use [the Nginx template](nginx.conf.example) as a starting point. Replace its example host, certificate paths, static root, and private backend address with actual staging values, run `nginx -t`, and verify proxy upgrades and TLS in a browser. The template now supplies `X-Forwarded-For` from the direct client address; only the known proxy IP may send trusted forwarded headers to Uvicorn. Do not expose the backend port, internal counters, PostgreSQL, or private environment files publicly. Use a separate staging PostgreSQL role/database and test-only accounts.

Current blockers: no staging host or certificate identified; no separate staging database or backup target identified; no staging test account or secure secret store identified; no browser automation package configured; Azure TTS credentials are absent, so Azure speech cannot be live-tested. A local Groq key exists, but no billable live request was made for Phase 14. Chrome and Edge binaries are installed. A local headless Chrome attempt against a temporary Vite server returned no DOM output, so even that limited browser smoke is **NOT VERIFIED**; it supplies no staging or audio evidence.

## Staging environment checklist

- [ ] Confirm a real staging DNS name and valid certificate. Redirect HTTP to HTTPS; `wss://` must use the same host.
- [ ] Build `frontend/dist` with `VITE_API_BASE_URL` unset. Never put database, Groq, Azure, or session values in a `VITE_` variable.
- [ ] Set private backend `APP_ENV=production`, `PUBLIC_ORIGIN` to the exact staging HTTPS origin, and `CORS_ORIGINS` to a JSON array containing only that origin. No wildcard credentialed CORS.
- [ ] Set `DATABASE_URL` to a **dedicated staging** `postgresql+asyncpg` database and `GROQ_API_KEY` through the host's secret manager. Keep `.env` out of Git and avoid printing values.
- [ ] Enable Azure only if both `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` exist. Browser voice mode can be tested without Azure. There is no separate session-signing secret: sessions use random opaque tokens, with hashes stored in PostgreSQL.
- [ ] Review `AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`, session days, pool size/overflow/timeouts, Groq timeout/retries, per-process provider slots, WebSocket limits, and rate limits. Production cookies must be Secure and HttpOnly for the session.
- [ ] Start one persistent ASGI process initially. Set `--proxy-headers --forwarded-allow-ips` to the actual proxy IP only. Keep `--ws-max-size` aligned with `WS_MAX_AUDIO_BYTES`; bound proxy body size and connection lifetime.
- [ ] Deploy `shared/languages.json` at the relative location expected by the backend. Configure private JSON log retention and alerting; the in-memory counters are per process and are not exposed publicly.
- [ ] Take a staging backup, validate database identity, then apply migrations once. Run readiness and smoke checks afterward.

From the staged `backend/` directory, after private variables are loaded, check settings without printing secrets:

```sh
python -c "from app.core.config import Settings; Settings().validate_deployment(); print('Production-mode configuration accepted')"
python -m alembic current
python -m alembic upgrade head --sql > /tmp/talkbuddy-staging-review.sql
# Review the SQL and backup first. Apply only to the confirmed staging database:
python -m alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws websockets --ws-max-size 1048576 --ws-max-queue 4 --proxy-headers --forwarded-allow-ips ACTUAL_PROXY_IP
```

`validate_deployment()` checks settings only; it does not prove connectivity or key validity. `alembic current` and `/api/health/ready` check PostgreSQL. Do not run migration or restore commands against an unverified target. The frontend and `/api`/`/ws` must share the public origin for the existing cookie/CSRF design.

## Repeatable staging HTTP/WSS smoke

[`backend/scripts/staging_smoke.py`](../backend/scripts/staging_smoke.py) performs non-destructive HTTP and WebSocket checks with an **existing dedicated staging test account**: frontend index, liveness/readiness, unauthorized API, rejected Origin/CORS, login, Secure+HttpOnly cookie, CSRF rejection, authenticated API/WSS, rejected WSS Origin, and logout revocation. It makes no AI request, captures no audio, and prints only check names and status. It is not a browser E2E test.

Run only after checking that `STAGING_ORIGIN` points to the authorized staging host; supply values privately and do not paste them into issue comments or logs:

```powershell
$env:STAGING_ORIGIN = 'https://ACTUAL_STAGING_HOST'
$env:STAGING_TEST_EMAIL = '<dedicated staging test account>'
$env:STAGING_TEST_PASSWORD = '<private password>'
$env:STAGING_CONFIRM = '1'
cd backend
.\.venv\Scripts\python.exe scripts\staging_smoke.py
Remove-Item Env:STAGING_TEST_PASSWORD,Env:STAGING_TEST_EMAIL,Env:STAGING_ORIGIN,Env:STAGING_CONFIRM
```

The script exits without network traffic unless all variables and the explicit confirmation are present. A passing script still requires browser and real-audio checks below.

## Browser and real-device test procedure

Record browser name/version, Windows version, microphone name, target language, TTS mode and voice, stage revision, time, and tester for every run. Use a dedicated staging account. Capture screenshots of controls and diagnostics, not private speech content. Preserve only test phrases in approved evidence storage.

1. In Chromium, load the staged origin, register a test-only account if needed, log in, navigate to `/microphone` and `/meeting`, and verify persistent session plus protected navigation. Test invalid login, permission denial, and logout.
2. On `/microphone`, grant permission to the explicitly chosen device. Verify input level, speech onset/end, completed WAV submission, WebSocket `processing`/`result`, and local translated playback. Run English → Hindi and English → Marathi separately. Check missing voice warning if applicable.
3. On `/meeting`, explicitly choose a browser tab with speech and enable tab audio. Verify captured level, phrase completion, translated captions, local playback, and cleanup after Stop or ending sharing. Repeat Hindi and Marathi. Meeting sharing is not a broadcast path.
4. Test Start/Pause/Resume/Stop, Stop during an in-flight phrase, refresh, tab closure, device removal, network interruption, backend restart, expired/revoked session, provider timeout/rate limit (only with a controlled staging fault), and browser background behavior. Check no stale playback, duplicate phrase, reconnect storm, unbounded queue, or orphan capture track.
5. Run at least one 10-minute session with repeated phrases. Monitor browser memory and queue depths, server logs/counters, database pool, and provider errors. Record failures as failures rather than excluding them from latency samples.

Existing Vitest/jsdom tests cover deterministic UI transitions and mocked capture/socket behavior. They do **not** prove a real browser permission prompt, physical microphone, meeting-tab audio, Groq output, or TTS audibility. No Playwright suite or staging browser E2E run was performed in this workspace.

## Latency evidence protocol

The Live Meeting diagnostics panel holds the **last 30** phrase timing records in memory. Before each language pair, press **Reset**, run at least 30 valid short phrases where practical, then choose **Download timings**. The CSV contains only numeric timings and chunk IDs; it excludes transcript text, audio, cookies, and user identity. Keep failed/dropped phrase counts separately, along with browser/device/network context. A refresh clears timings. Run Hindi and Marathi as separate sessions and name each exported file accordingly.

For each pair, report valid and failed phrase counts, caption and playback average/p50/p95, STT and translation durations, TTS preparation where available, playback queue wait, and the slowest measured stage. A blank CSV field means **unavailable**, not zero. Browser speech-end to caption/playback uses browser monotonic timing; server STT/translation durations are reported separately. Never subtract raw clocks from different machines. Speech end is VAD-estimated; browser voice events and autoplay policies may leave playback timing unavailable. The p50 caption target below 2 seconds is an engineering goal, not a measured result. **No real latency numbers were collected in Phase 14.**

## Security, backup, and operational checks

- Confirm `http://` redirects to `https://` and browser `wss://` succeeds; inspect TLS and proxy headers. Check session cookie Secure, HttpOnly, SameSite; CSRF rejection; trusted and untrusted HTTP/WS Origins; unauthorized `/api/auth/me`; logout revocation; oversized WAV; safe provider errors; readiness 503 during a controlled database outage; and no secret/transcript/audio in application logs.
- Test session expiry and provider failures in a controlled staging environment, not by changing production accounts or exhausting real provider quotas. In-memory rate limits are per process, not distributed.
- Configure PostgreSQL `pg_service.conf` entries (or a managed secret mechanism) for **separate** staging and disposable restore databases. Verify identity before each command. Do not pass passwords on the command line.

```sh
psql 'service=STAGING_SERVICE' -c 'SELECT current_database(), current_user;'
pg_dump --format=custom --no-owner --dbname='service=STAGING_SERVICE' --file=talkbuddy-staging.backup
pg_restore --list talkbuddy-staging.backup
psql 'service=DISPOSABLE_RESTORE_SERVICE' -c 'SELECT current_database(), current_user;'
# Destructive ONLY to the verified disposable restore database:
pg_restore --clean --if-exists --no-owner --dbname='service=DISPOSABLE_RESTORE_SERVICE' talkbuddy-staging.backup
```

After restore, point a separate application instance at the disposable restore database and check `/api/health/ready`, Alembic version, and non-sensitive test records. Never restore over the active staging or production database for this validation. For rollback, redeploy the previous application artifact if compatible; do not assume Alembic downgrade is data-safe. Use a verified backup or forward repair for a failed schema change. **Backup, restore, migration against staging, and outage recovery were not performed in this workspace.**

## Release evidence matrix — 2026-11-19

`PASS` means the named scope has recorded evidence. Automated/mock results are kept separate from live checks.

| Test | Status | Evidence |
| --- | --- | --- |
| Local backend pytest | PASS | 210 passed, 2 skipped (live Groq and dedicated PostgreSQL); one Starlette TestClient deprecation warning. |
| Local frontend tests, TypeScript, build | PASS | Isolated run: 104 passed; typecheck and Vite build passed. One history test timed out during a concurrent run, then passed in the isolated full run. |
| Local desktop regression and offline Alembic | PASS | 51 desktop tests passed under concurrent load after the deterministic test fix; both migrations rendered offline. `pip check` and Python compile checks passed. |
| Staging HTTPS | NOT VERIFIED | No staging host/certificate supplied. |
| Local Chrome page-load attempt | NOT VERIFIED | Headless CLI returned no DOM output; no browser success was observed. |
| Staging WSS | NOT VERIFIED | No staging endpoint or test account supplied. |
| Login and logout in a browser | NOT VERIFIED | Existing mocked UI tests are not a staging browser run. |
| Microphone translation | NOT VERIFIED | No real browser/audio run. |
| Meeting-tab translation | NOT VERIFIED | No real tab sharing run. |
| Hindi captions | NOT VERIFIED | No staging phrase observed. |
| Marathi captions | NOT VERIFIED | No staging phrase observed. |
| Hindi speech | NOT VERIFIED | No local playback observed. |
| Marathi speech | NOT VERIFIED | No local playback observed. |
| 10-minute reliability | NOT VERIFIED | No timed staging session. |
| p50/p95 latency | NOT VERIFIED | No real phrase measurements. |
| Provider recovery | NOT VERIFIED | No controlled staging failure test. |
| Backup and restore | NOT VERIFIED | No separate staging/restore databases. |
| Security checks in staging | NOT VERIFIED | Existing automated tests do not prove deployed TLS/cookies/proxy. |
| GitHub Actions | NOT VERIFIED | Hosted workflow run not inspected. |

**Release decision: NOT READY.** Real microphone, meeting-tab, Hindi/Marathi speech, deployed security, long-session reliability, latency, and backup/restore gates remain unverified. The decision can change only after a staging run records evidence for each mandatory gate. No production deployment is authorized by this document.
