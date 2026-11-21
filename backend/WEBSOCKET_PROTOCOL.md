# TalkBuddy WebSocket translation protocol (Phases 5–6)

The endpoint is `WS /ws/translate`. It processes finalized complete audio files in arrival order. This is chunked request/response translation, not continuous audio streaming. Experimental interim captions use additional complete WAV snapshots and do not change final result ordering.

The React local meeting listener uses this existing protocol. Browser tab capture requires user approval through `getDisplayMedia`; an `AudioWorklet` detects pauses and encodes each complete phrase as an independent PCM WAV message. The backend handles finalized phrases sequentially and returns a result only after transcription and translation finish. It does not receive video frames or inject translated speech into the meeting. Browser `speechSynthesis` performs ordered, local playback. See [frontend meeting setup and limits](../frontend/README.md#local-meeting-listener).

## Authentication and handshake

1. Log in through `POST /api/auth/login` first. The browser sends the HTTP-only `talkbuddy_session` cookie during the WebSocket handshake. Do not put a token or user ID in the URL or message body.
2. The client must send an `Origin` header. In production it must match configured `PUBLIC_ORIGIN` (the same HTTPS origin that serves the frontend and proxies `/ws`). Development also accepts the configured exact origins. Browsers set this header automatically. The REST `X-CSRF-Token` header is not used for WebSockets. The server never trusts a supplied `Host` header as the production origin.
3. The server checks the database session before accepting the connection. It rechecks the session on every received message and before and after translation. Expired or revoked sessions are closed.
4. At most `WS_MAX_CONNECTIONS_PER_USER` sockets per user are allowed in one server process.

The server requests close code `1008` for authentication or origin failure, or `1013` when the connection limit is reached. Because these happen before acceptance, browsers may show a failed handshake rather than a close event with that code. The server never returns credentials or session tokens in messages.

## Client messages

First send one UTF-8 JSON `start` message:

```json
{"type":"start","target_language":"fr","source_language":"en","audio_format":"wav"}
```

`target_language` is required. `source_language` is optional; omit it to let Whisper detect the language for each phrase. Both accept English (`en`), Hindi (`hi`), Marathi (`mr`), Spanish (`es`), German (`de`), French (`fr`), Japanese (`ja`), Russian (`ru`), Mandarin Chinese (`zh-CN`), and Korean (`ko`), or their names. A manually selected source is sent as Whisper's language hint and remains the translation hint even if provider metadata differs. The `zh-CN` source hint is sent to Whisper as ISO-639-1 `zh`. `audio_format` must be `wav` for this MVP. Unknown fields, including client-supplied user IDs, are rejected.

Saving is disabled by default. To save results, first set `save_history_enabled: true` through `PATCH /api/preferences`, then create a translation session with matching `target_language`. Start the socket with:

```json
{"type":"start","target_language":"fr","audio_format":"wav","save_history":true,"session_id":"SESSION_UUID"}
```

For a saving connection, precede **each** binary chunk with a JSON metadata message containing a client-generated UUID:

```json
{"type":"chunk","request_id":"REQUEST_UUID"}
```

The next binary message consumes that ID. Retrying the same ID and identical audio returns the saved result without another provider call. Reusing an ID with different audio returns `idempotency_conflict`. A saving start requires a valid owned, open session and enabled preference. The server rechecks consent and ownership for each save. Without saving, send binary chunks directly after `ready`, as before.

After `ready`, send each complete, independently decodable **PCM WAV file** as one binary WebSocket message. Recommended encoding is mono, 16 kHz, 16-bit PCM. Each binary message must contain its own RIFF/WAVE header and complete frames. Raw PCM fragments, a partial WAV stream, and browser `MediaRecorder` fragments are not valid chunks.

To end the connection, send:

```json
{"type":"stop"}
```

The server processes messages sequentially. A `stop` already queued behind an in-flight chunk takes effect after that chunk finishes, then the server closes with code `1000`.

### Optional generated speech audio

The existing text-only protocol remains the default. A browser or optional desktop client can add `"synthesize_speech":true` to `start`. This requires private `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `AZURE_SPEECH_ENDPOINT`, and explicit `AZURE_TTS_ENABLED=true` on the backend; without them the server returns a recoverable `speech_unavailable` error instead of `ready`. The browser client resends `start` without synthesis on the same authenticated socket and uses a matching browser voice or captions. Browser WebSockets use the existing HTTP-only session cookie and allowed Origin. Desktop clients can obtain an in-memory session with the existing `/api/auth/login` endpoint; no token belongs in a URL. Remote connections require HTTPS/WSS and trusted TLS certificates.

After each `result`, an opted-in client receives exactly one further JSON message with the same `chunk_id`: either `speech_audio` or `speech_error`. Wait for it before sending the next WAV phrase to preserve playback order. The browser client validates this WAV, queues playback locally, and does not send it into another application. Speech audio is **generated translated speech**, never microphone audio:

```json
{"type":"speech_audio","chunk_id":1,"audio_format":"wav","audio_base64":"...","preparation_time_ms":420}
```

The decoded audio is 24 kHz, mono, 16-bit PCM WAV, capped at `TTS_MAX_AUDIO_BYTES` (default 2 MiB) and 30 seconds. `speech_error` contains `type`, `chunk_id`, `code`, and a generic `message`; translated text in the preceding `result` remains usable. TTS text is capped at 500 characters. Speech synthesis is an optional Azure Speech service call, so provider availability, voice availability, billing, and latency are separate from Groq translation. No audio is saved. Browsers that omit `synthesize_speech` receive no extra messages.

## Server messages

### Experimental interim captions (Phase 19)

Interim captions are **disabled by default** and require both backend `WS_INTERIM_ENABLED=true` and frontend `VITE_INTERIM_CAPTIONS_ENABLED=true`. The user must also check **Experimental interim captions** before starting a browser session. The client adds `"interim_captions":true` to `start`; the server replies with `"interim_captions":true` in `ready` only when enabled. If requested but unavailable, `ready` contains `false` and the client continues with final captions only. Existing clients that omit the option receive the original `ready` shape.

For each active phrase snapshot, send a JSON header immediately followed by one complete binary 16 kHz, mono, 16-bit PCM WAV. No base64 audio is placed in JSON:

```json
{"type":"interim_audio","phrase_id":"PHRASE_UUID","revision":1,"audio_format":"wav"}
```

The response is either `{"type":"interim_caption","phrase_id":"PHRASE_UUID","revision":1,"text":"Today we are","is_final":false,"detected_language":"en"}` or `{"type":"interim_error","phrase_id":"PHRASE_UUID","revision":1,"code":"provider_timeout","message":"Interim transcription timed out; final captions continue"}`. The client replaces prior revisions for the same phrase and ignores stale or post-final responses. To cancel an active preview, send `{"type":"interim_cancel","phrase_id":"PHRASE_UUID"}`. Final binary WAV messages keep the existing protocol and cancel an in-flight interim task before final processing. Interim audio and captions are never translated, spoken, saved, or exported.

The browser sends at most four cumulative snapshots per phrase, nominally 1.8 seconds apart (configurable between 1.5 and 5 seconds). The backend accepts at most 50 interim requests per connection by default, at least 1.5 seconds apart, with at most one in flight; each snapshot is at most 256,000 bytes and 0.5–8 seconds, and processing times out after 8 seconds. `WS_INTERIM_*` settings can adjust these bounds. Rejected previews produce `interim_error` and do not interrupt final caption processing. Every accepted snapshot is another Groq Whisper request and may incur charges; the feature stays off until real-device and cost verification. This is periodic transcription, not native streaming STT.

After valid `start`:

```json
{"type":"ready","target_language":"fr","source_language":"en","audio_format":"wav"}
```

For each valid binary chunk, the server sends `processing`, followed by `result` or `error`:

```json
{"type":"processing","chunk_id":1}
```

```json
{"type":"result","chunk_id":1,"original":"Hello","translated":"Bonjour","detected_language":"en","language_detection_source":"stt","target_language":"fr","processing_time_ms":842}
```

`chunk_id` starts at 1 and increases for accepted chunks. `detected_language` is the normalized provider-reported language code when recognized, including supported extra source codes such as `it`, or `null` if metadata is missing or unrecognized. `language_detection_source` is `stt` or `unknown` in new responses; older clients can ignore it. `stt` means the value came from the transcription response, which may have been influenced by an explicit source hint. No confidence score is invented. Recognition is phrase-level and mixed-language speech is best effort. When reliable detected source and target match, the original text is returned unchanged and the translation LLM is skipped. `processing_time_ms` measures backend processing, including provider calls; it is not an end-to-end latency guarantee.

If STT succeeds but translation fails, `error` may also include `chunk_id`, `original`, `detected_language`, and `language_detection_source`. The browser can keep the original caption while showing that translation is unavailable. These fields are omitted for errors that occur before transcription.

The browser keeps a UUID for each completed phrase and associates it with the server's per-connection `chunk_id` through its single in-flight final request. With interim captions enabled, the UUID is sent as `phrase_id` for preview correlation; it is not persisted. `chunk_id` restarts on a new connection. On disconnect, unsent and in-flight phrases are discarded instead of replayed; exactly-once processing cannot be inferred from a dropped connection. Saved-history `request_id` remains the existing server-side idempotency key for explicitly opted-in text history.

New results include `transcription_time_ms` and `translation_time_ms`, measured around the corresponding provider service calls. `processing_time_ms` includes those calls, database checks, and optional history saving. These are server-side measurements; clients should measure from sending a binary chunk to receiving its result for their own total response latency. Retried results served from history omit the provider timings. The configured provider semaphore limits concurrent Groq calls across REST and WebSocket requests in one process.

These stage timings use the backend's monotonic clock and include any wait for its provider concurrency slot and the provider request. They are optional, numeric durations only. No wall-clock timestamp, audio, credential, or user identifier is added for diagnostics. The browser uses its own monotonic clock for capture, WebSocket round trip, and playback. Never subtract a backend clock value from a browser clock value.

At DEBUG log level, the WebSocket handler records numeric WAV validation, result-send, STT/translation, and optional speech-audio send durations tagged with its per-connection `chunk_id`. It does not log audio, transcript text, credentials, cookies, or provider response bodies. The backend cannot include its own result-send completion duration inside the result it has already sent. `speech_audio.preparation_time_ms` measures optional Azure preparation before the WAV is sent; it is a server duration and should not be subtracted from browser timestamps.

When saving is enabled, `result` also includes `"saved":true` and `"message_id":"MESSAGE_UUID"`. Only completed translations are stored; audio is discarded. A failed or silent chunk has no history record. Saved messages can be read at `GET /api/history/{session_id}` and removed with `DELETE /api/history/{session_id}` or `DELETE /api/history` using the REST CSRF header.

Errors have a stable shape:

```json
{"type":"error","code":"invalid_audio","message":"Invalid or incomplete WAV chunk","recoverable":true}
```

Recoverable codes include `invalid_message`, `invalid_start`, `invalid_state`, `unsupported_language`, `unsupported_audio_format`, `invalid_audio`, `audio_too_large`, `no_speech`, `invalid_input`, `provider_timeout`, `provider_unavailable`, `provider_error`, `processing_timeout`, `missing_request_id`, `history_disabled`, `history_session_invalid`, `history_session_ended`, `idempotency_conflict`, and `storage_unavailable`. The client may send a corrected chunk or control message after a recoverable error. Non-recoverable errors such as `session_invalid`, `session_check_failed`, `chunk_limit`, `idle_timeout`, and `internal_error` close the connection.

## Limits and local test

Defaults: 1 MiB per audio chunk, 2 KiB per control message, 100 accepted chunks per connection, 2 connections per user per process, 60 seconds idle timeout, and 120 seconds processing timeout per chunk. Configure them with `WS_*` environment variables. Run Uvicorn with a bounded WebSocket queue and frame size:

```powershell
uvicorn app.main:app --reload --ws websockets --ws-max-size 1048576 --ws-max-queue 4
```

If you change `WS_MAX_AUDIO_BYTES`, keep `--ws-max-size` aligned with it. TestClient tests exercise the protocol without contacting Groq. For a local manual test, log in at `http://127.0.0.1:8000/docs`, then run this in that page's browser console and choose a short PCM WAV file under 1 MiB:

```javascript
const socket = new WebSocket(`ws://${location.host}/ws/translate`);
socket.onopen = () => socket.send(JSON.stringify({type: "start", target_language: "fr", audio_format: "wav"}));
socket.onmessage = async (event) => {
  const message = JSON.parse(event.data);
  console.log(message);
  if (message.type === "ready") {
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = ".wav";
    picker.onchange = async () => socket.send(await picker.files[0].arrayBuffer());
    picker.click();
  }
  if (message.type === "result") socket.send(JSON.stringify({type: "stop"}));
};
```

For HTTPS, the browser uses `wss://` instead of `ws://`. Audio is never stored; results are stored only with explicit consent and request opt-in. Connection and provider limits are per process; a shared limiter is needed across multiple workers. A reverse proxy should also impose an HTTP/WebSocket connection and body-size limit. Restrict `CORS_ORIGINS` to exact trusted origins and use HTTPS in production.
