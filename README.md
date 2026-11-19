# TalkBuddy

TalkBuddy is a browser-first speech translation application with a FastAPI backend and a React frontend. The backend provides async PostgreSQL, cookie authentication, Groq transcription and translation, WebSocket phrase translation, optional Azure speech generation, and opt-in text history. The frontend offers a microphone translator and a user-authorized meeting-tab listener with local captions and speech playback.

**The browser product requires no desktop bridge, VB-CABLE, Python desktop process, or Windows audio device.** The separate [Windows desktop bridge](desktop_bridge/README.md) is an optional experimental integration. It does not affect browser translation. TalkBuddy does not inject translated audio into Google Meet, Zoom, or other calling applications. The [ten-language registry](shared/languages.json) drives backend validation and frontend selectors; browser speech requires a matching installed voice, while Azure speech is optional and requires backend credentials.

## Requirements

- Python 3.11 or newer
- PostgreSQL for database setup and `/api/health/db`
- A Groq API key for the `/api/ai/*` endpoints

The API can start and `/api/health` works without PostgreSQL. `/api/health/db` returns HTTP 503 until the database is configured and reachable.

## Install and run

From the repository root, in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uvicorn app.main:app --reload --ws websockets --ws-max-size 1048576 --ws-max-queue 4
```

On macOS or Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, and `cp .env.example .env` instead. Ensure the `python` command used to create the environment runs Python 3.11 or newer.

The server listens at `http://127.0.0.1:8000`. Check `GET http://127.0.0.1:8000/api/health` for `{"status":"ok"}`. Once PostgreSQL is configured, `GET http://127.0.0.1:8000/api/health/db` also returns `{"status":"ok"}`. Interactive API docs are at `http://127.0.0.1:8000/docs`.

## Configuration

The backend reads `backend/.env` and process environment variables. Copy `backend/.env.example` to `backend/.env` for local development. Process environment variables take precedence. `CORS_ORIGINS` is a JSON array of allowed browser origins; set it to the exact origins that need access. Development also allows the exact Vite origins `http://127.0.0.1:5173` and `http://localhost:5173`; production requires an explicit allowlist. Restart FastAPI after changing `.env`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` | API title | `TalkBuddy API` |
| `APP_ENV` | Runtime environment | `development` |
| `LOG_LEVEL` | Application log level | `INFO` |
| `CORS_ORIGINS` | Allowed CORS origins as a JSON array | `[]` |
| `DATABASE_URL` | Async PostgreSQL connection URL | Unset |
| `DATABASE_POOL_SIZE` | Pooled PostgreSQL connections per process | `5` |
| `DATABASE_MAX_OVERFLOW` | Temporary extra connections per process | `5` |
| `DATABASE_POOL_TIMEOUT_SECONDS` | Maximum wait for a pooled connection | `5` |
| `DATABASE_COMMAND_TIMEOUT_SECONDS` | PostgreSQL command timeout | `15` |
| `AUTH_SESSION_DAYS` | Server session and cookie lifetime | `7` |
| `AUTH_LOGIN_RATE_LIMIT` | Login attempts per client IP per window | `10` |
| `AUTH_REGISTER_RATE_LIMIT` | Registration attempts per client IP per window | `5` |
| `AUTH_RATE_WINDOW_SECONDS` | Rate-limit window length | `60` |
| `AUTH_COOKIE_SECURE` | HTTPS-only cookie override; always on in production | Off in development |
| `AUTH_COOKIE_SAMESITE` | Cookie SameSite policy (`lax` or `strict`) | `lax` |
| `GROQ_API_KEY` | Groq API key; set only in the private `.env` | Unset |
| `GROQ_TRANSCRIPTION_MODEL` | Groq speech model | `whisper-large-v3-turbo` |
| `GROQ_TRANSLATION_MODEL` | Groq chat model | `openai/gpt-oss-20b` |
| `GROQ_TIMEOUT_SECONDS` | Per-request provider timeout | `45` |
| `GROQ_MAX_RETRIES` | Provider SDK retries for transient errors | `2` |
| `AZURE_SPEECH_KEY` | Optional Azure translated speech key; keep in private `.env` | Unset |
| `AZURE_SPEECH_REGION` | Matching Azure Speech resource region | Unset |
| `TTS_TIMEOUT_SECONDS` | Optional speech-generation timeout | `20` |
| `TTS_MAX_AUDIO_BYTES` | Maximum generated WAV response | `2097152` (2 MiB) |
| `AI_MAX_AUDIO_BYTES` | Maximum accepted audio upload | `10485760` (10 MiB) |
| `AI_MAX_TEXT_CHARS` | Maximum translation input length | `5000` |
| `AI_MAX_CONCURRENT_PROVIDER_CALLS` | Maximum simultaneous Groq calls per process across REST and WebSockets | `8` |
| `AI_PROVIDER_QUEUE_TIMEOUT_SECONDS` | Maximum wait for a provider slot | `5` |
| `WS_MAX_AUDIO_BYTES` | Maximum binary WAV chunk | `1048576` (1 MiB) |
| `WS_MAX_CONTROL_BYTES` | Maximum JSON control message | `2048` |
| `WS_MAX_CONNECTIONS_PER_USER` | Connections per user per process | `2` |
| `WS_MAX_CHUNKS` | Accepted chunks per connection | `100` |
| `WS_IDLE_TIMEOUT_SECONDS` | Idle socket timeout | `60` |
| `WS_PROCESSING_TIMEOUT_SECONDS` | Processing timeout per chunk | `120` |

## PostgreSQL setup on Windows

Install PostgreSQL if needed and start its Windows service. Open **SQL Shell (psql)** or run `psql -U postgres -h localhost -d postgres` in PowerShell if `psql` is on your `PATH`. Then create a dedicated local role and database:

```sql
CREATE ROLE talkbuddy_user LOGIN;
\password talkbuddy_user
CREATE DATABASE talkbuddy_db OWNER talkbuddy_user;
```

The `\password` command prompts for a password without putting it in shell history. Edit `backend/.env` so `DATABASE_URL` contains the role's password, for example `postgresql+asyncpg://talkbuddy_user:YOUR_PASSWORD@localhost:5432/talkbuddy_db`. Percent-encode special characters in the password when placing them in a URL. Never commit `.env`.

From `backend/`, verify the connection **before** applying the migration:

```powershell
python -m alembic current
python -m alembic upgrade head
```

`alembic current` must exit successfully before running `upgrade head`. To inspect the SQL without connecting or changing the database, run `python -m alembic upgrade head --sql`. For later schema changes, generate a revision against a configured development database with `python -m alembic revision --autogenerate -m "describe change"`, review it, and then apply it with `python -m alembic upgrade head`.

Alembic manages the schema; the application does not create a database or tables automatically.

## Authentication API

Start the server from `backend/` with `uvicorn app.main:app --reload`, then open `http://127.0.0.1:8000/docs`.

1. Call `POST /api/auth/register` with `name`, `email`, and a password of 12 to 128 characters. It returns HTTP 201 and public user fields. Registration does not log the user in.
2. Call `POST /api/auth/login` with `email` and `password`. It sets an HTTP-only `talkbuddy_session` cookie and a readable `talkbuddy_csrf` cookie. The JSON response contains public user fields only.
3. Call `GET /api/auth/me` in the same browser to verify the session.
4. For `POST /api/auth/logout`, copy the `talkbuddy_csrf` cookie value into the `X-CSRF-Token` header. The server revokes the session and clears both cookies.

Swagger UI sends same-origin cookies automatically. In an HTTP client, preserve cookies between requests and send the CSRF header on logout. Browser writes from untrusted origins are rejected; registration and login require JSON requests. Login failures return the same message whether the email is unknown or the password is wrong.

The session cookie uses `HttpOnly`, `SameSite=lax` by default, and `Secure` when `APP_ENV=production`. For local HTTP development, `Secure` is off unless explicitly enabled. Production requires HTTPS. Login and registration rate limits currently apply per client IP and per server process; use a shared limiter when running multiple workers or instances.

## AI speech translation API

Set `GROQ_API_KEY` in the private `backend/.env`, start the server, and use `http://127.0.0.1:8000/docs`. Log in first. For each AI POST request, copy the readable `talkbuddy_csrf` cookie value into the `X-CSRF-Token` header. The browser sends the HTTP-only session cookie automatically.

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST /api/ai/transcribe` | Multipart `audio` file | `text`, `detected_language` |
| `POST /api/ai/translate` | JSON `{"text":"Hello","target_language":"fr"}` | `original_text`, `translated_text`, `target_language` |
| `POST /api/ai/speech-translate` | Multipart `audio` file and `target_language` form field | Both texts, detected language, target language |

Target languages are English (`en`), Hindi (`hi`), Marathi (`mr`), Spanish (`es`), German (`de`), French (`fr`), Japanese (`ja`), Russian (`ru`), Mandarin Chinese (`zh-CN`), and Korean (`ko`). Names such as `French` and `Chinese (Mandarin)` are also accepted. Whisper receives `zh` rather than `zh-CN` as a source-language hint. Audio uploads support FLAC, MP3, MP4/M4A, MPEG/MPGA, OGG, WAV, and WebM with matching media types and file signatures. Empty, oversized, or unsupported uploads are rejected before calling Groq. The application never persists raw audio. Translation results are saved only with explicit opt-in; see below.

The backend reads [`shared/languages.json`](shared/languages.json) at startup. Deploy that file alongside `backend/` and `frontend/`; a backend-only copy without the shared registry cannot start. Browser speech tags in the registry are voice-selection hints, not a guarantee that a particular machine has the voice installed.

Groq SDK calls have a configurable timeout and at most three configured retries. Provider failures return generic errors without API keys or internal details. Language detection depends on the transcription model's returned metadata, so `detected_language` can be `null`. AI translation is model-generated and should be reviewed for sensitive or high-stakes use.

## WebSocket chunk translation

`WS /ws/translate` uses the login session cookie and a strict browser `Origin` check. Send one JSON `start` message, then complete PCM WAV files as binary messages, then JSON `stop`. The server processes chunks sequentially and returns `ready`, `processing`, `result`, or `error` messages. See [the WebSocket protocol and local test](backend/WEBSOCKET_PROTOCOL.md). This is chunk processing; no continuous stream or measured latency guarantee is claimed.

## Preferences, sessions, and history

All endpoints below require the login cookie. For `POST`, `PATCH`, and `DELETE`, send the readable `talkbuddy_csrf` cookie value as `X-CSRF-Token`. Swagger UI at `/docs` can exercise these endpoints after login. A fresh user has `source_language: "auto"`, `target_language: "en"`, `speech_rate: 1.0`, and `save_history_enabled: false`. Valid languages are en, hi, mr, es, de, fr, ja, ru, zh-CN, and ko; `speech_rate` is 0.5â€“2.0. The frontend uses this rate for browser speech playback.

| Endpoint | Use |
| --- | --- |
| `GET /api/preferences` | Read preferences and history consent |
| `PATCH /api/preferences` | Update any preference, for example `{"target_language":"fr","save_history_enabled":true}` |
| `POST /api/translation-sessions` | Create a session with optional `title`, `source_language`, and `target_language`; omitted languages use preferences |
| `PATCH /api/translation-sessions/{session_id}` | Change `title` with `{"title":"Conversation"}`; `null` clears it |
| `POST /api/translation-sessions/{session_id}/end` | Mark the session ended; later saves to it are rejected |
| `GET /api/history?limit=20&offset=0&order=newest` | List owned sessions; `order` is `newest` or `oldest` |
| `GET /api/history/{session_id}?limit=50&offset=0&order=oldest` | Read an owned session and a page of messages |
| `DELETE /api/history/{session_id}` | Delete a session and its messages; returns 204 |
| `DELETE /api/history` | Delete all your sessions and messages; returns `deleted_sessions` |

History list and message page limits are 1â€“100; offsets are 0â€“100000. Invalid UUIDs and pagination values return 422. Missing or other users' sessions return 404. Deletion is permanent; disable saving with `PATCH /api/preferences` and `{"save_history_enabled":false}` to stop future saves. Disabling does not erase existing history.

Saving requires both the stored preference and an explicit per-request opt-in. First enable `save_history_enabled`, then create a session with the same target language as the translation. For text, send `POST /api/ai/translate` with `{"text":"Hello","target_language":"fr","save_history":true,"session_id":"SESSION_UUID"}` and an `Idempotency-Key: REQUEST_UUID` header. For audio, send `save_history` and `session_id` as multipart fields to `POST /api/ai/speech-translate`, with the same header. Successful saved responses include `saved: true` and `message_id`. A retry with the same UUID and identical input returns the stored result; reusing the UUID for different input returns 409. Requests without opt-in remain unsaved. Failed translations are not saved. `POST /api/ai/transcribe` never saves history.

For WebSocket saving, include `save_history: true` and `session_id` in `start`. Before each binary audio message, send a JSON `chunk` message containing a unique `request_id` UUID. See [WEBSOCKET_PROTOCOL.md](backend/WEBSOCKET_PROTOCOL.md). The server stores translated text and a SHA-256 request fingerprint for retry detection, never the audio bytes. History is private to the authenticated user.

After updating an existing installation, run `python -m alembic current` from `backend/` to verify connectivity, review `python -m alembic upgrade 20261115_01:20261115_02 --sql`, and run `python -m alembic upgrade head`. Phase 6 revision `20261115_02` adds one preference column, two message columns, a unique constraint, and two indexes. Existing tables remain in place.

## React frontend

The frontend is in a separate [`frontend/`](frontend/) folder. Start FastAPI first, then run these commands from `frontend/`:

```powershell
Copy-Item .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` and `/ws` to `VITE_BACKEND_URL` (`http://127.0.0.1:8000` by default), keeping browser cookies and CSRF on one origin. Both local Vite hostnames are allowed automatically in development. For production, serve the frontend and reverse-proxy both paths from the same HTTPS origin. See the [frontend setup and limitations](frontend/README.md). Build with `npm.cmd run build` and test with `npm.cmd test`.

The frontend offers a [microphone translator](frontend/README.md#browser-audio-modes) at `/microphone` and a [local meeting listener](frontend/README.md#local-meeting-listener) at `/meeting`. Both require an explicit browser permission prompt, use the same pause-based phrase segmentation, and support all ten target languages. Translated speech plays locally through a matching installed browser voice by default. Users can explicitly choose Azure speech when it is configured on the backend; missing credentials leave captions available through browser-voice mode. Neither mode broadcasts audio into a calling application.

The browser audio path batches capture blocks in AudioWorklet, bounds phrase and WebSocket queues, and cancels local capture/playback promptly on Stop. Expand **Diagnostics** on either audio route for separate caption and playback latency, server STT/translation time, queue depths, and dropped audio. See the [audio architecture](frontend/README.md#browser-audio-modes) and [Windows 11 manual test checklist](frontend/README.md#windows-11-and-chromium-manual-audio-checklist). No real-device latency target or calling-app playback is claimed from automated tests.

## Tests

From `backend/` with the virtual environment active:

```powershell
python -m pytest
```

Routine tests use mocked Groq calls and isolated SQLite data. The dedicated PostgreSQL test runs only when `TEST_DATABASE_URL` is set. Use a separate disposable database whose name contains `test`; the test rejects the configured development database name and deletes only users it created. In PowerShell, set the test URL in your current shell and run:

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://talkbuddy_test_user:YOUR_PASSWORD@localhost:5432/talkbuddy_test_db"
python -m pytest -q -m postgres
Remove-Item Env:TEST_DATABASE_URL
```

Create the test role and database with a PostgreSQL administrator before running this command. For example, in `psql`:

```sql
CREATE ROLE talkbuddy_test_user LOGIN;
\password talkbuddy_test_user
CREATE DATABASE talkbuddy_test_db OWNER talkbuddy_test_user;
```

The test applies migrations to that database, then exercises registration, login, rollback after a duplicate email, preferences, session creation and revocation, owned history, idempotent saves, cross-user access denial, and deletion. Never point `TEST_DATABASE_URL` at a development or production database. `python -m alembic check` checks model and migration alignment against the database configured by `DATABASE_URL`.

An optional live Groq translation smoke test makes a billable request only when explicitly selected and enabled. Set the private `GROQ_API_KEY` in `backend/.env`, then run:

```powershell
$env:RUN_LIVE_GROQ_TESTS = "1"
python -m pytest -q -m live_groq
Remove-Item Env:RUN_LIVE_GROQ_TESTS
```

The normal suite skips this test. Do not enable it in CI. Production should use HTTPS, an exact `CORS_ORIGINS` allowlist, a bounded reverse proxy body and WebSocket queue, and shared rate and concurrency controls when running multiple workers. Auth rate limits and provider limits currently apply per process; provider SDK timeouts and retries can make an in-flight call last longer than one configured timeout. WebSocket `result` messages expose server-side transcription, translation, and total processing times; client response latency should be measured at the client.

## Structure

```text
talkbuddy/
├── AGENTS.md
├── .gitignore
├── README.md
├── shared/
│   └── languages.json
├── desktop_bridge/
│   ├── README.md
│   ├── requirements.txt
│   ├── main.py
│   ├── audio_devices.py
│   ├── wav_player.py
│   ├── config.py
│   └── tests/
├── frontend/
│   ├── .env.example
│   ├── README.md
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── components/
│       ├── contexts/
│       ├── lib/
│       ├── pages/
│       └── test/
└── backend/
    ├── .env.example
    ├── requirements.txt
    ├── pytest.ini
    ├── alembic.ini
    ├── WEBSOCKET_PROTOCOL.md
    ├── alembic/
    │   ├── env.py
    │   └── versions/
    │       ├── 20261115_01_initial_schema.py
    │       └── 20261115_02_history_opt_in.py
    ├── app/
    │   ├── main.py
    │   ├── ai/
    │   ├── auth/
    │   ├── core/
    │   ├── db/
    │   ├── history/
    │   ├── ws/
    │   └── api/
    │       ├── ai.py
    │       ├── auth.py
    │       ├── health.py
    │       ├── history.py
    │       ├── preferences.py
    │       └── translation_sessions.py
    └── tests/
        ├── test_ai.py
        ├── test_auth.py
        ├── test_database.py
        ├── test_health.py
        ├── test_history.py
        ├── test_live_groq.py
        ├── test_postgres_integration.py
        ├── test_websocket.py
        └── test_ws_history.py
```

