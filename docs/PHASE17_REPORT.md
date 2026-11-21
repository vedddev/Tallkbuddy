# Phase 17 — Automatic source-language detection

## Implemented

- The existing **Detect automatically** source option now has visible, phrase-level results. With that option, the browser omits `source_language` from `start`, and the backend omits the Groq `language` hint. A manual source still goes to Whisper as its supported ISO-639-1 hint and remains the translation hint.
- The STT adapter reads `language` from Groq's `verbose_json` transcription response. Recognized provider labels are normalized; missing or unsupported labels become `null`. No translation LLM call is used to guess the source language.
- The existing WebSocket `result` keeps `detected_language` and adds optional `language_detection_source: "stt" | "unknown"`. Older clients can ignore the extra field. A translation error after successful transcription may include the original text and language metadata so the browser can retain the original caption. The combined REST speech-translation endpoint also includes the original transcription in its generic error response after a translation failure. Provider error details remain hidden.
- Original captions show the provider language per phrase, or **Unknown language**. Translated captions and speech keep the selected target language and ordering. A reliable same-language detection returns the original transcript unchanged, without calling the translation LLM. The combined REST speech-translation route uses the same source metadata and same-language shortcut.
- Existing authentication, Origin validation, CSRF handling, rate limits, history consent, queue bounds, reconnection, and Azure/browser/captions fallback remain in place. Raw audio is not persisted.

## Files modified for Phase 17

- Backend: `app/ai/languages.py`, `app/ai/service.py`, `app/api/ai.py`, `app/ws/protocol.py`, `app/ws/translate.py`, `tests/test_languages.py`, `tests/test_ai.py`, `tests/test_websocket.py`, `WEBSOCKET_PROTOCOL.md`.
- Frontend: `src/lib/detectedLanguage.ts`, `src/lib/types.ts`, `src/components/MeetingInterpreter.tsx`, `src/test/detectedLanguage.test.ts`, `src/test/meetingInterpreter.test.tsx`, `README.md`.
- This report. Existing uncommitted files from earlier phases were preserved.

## STT format and normalization

Groq transcription uses `response_format="verbose_json"`; a top-level provider `language` field is read when present. The optional `language` request parameter is omitted for automatic detection and sent for a manual source. See [Groq speech-to-text documentation](https://console.groq.com/docs/speech-to-text) and the [audio transcription API reference](https://console.groq.com/docs/api-reference).

Groq documents `verbose_json` and segment metadata, but its published Python [`Transcription` model](https://github.com/groq/groq-python/blob/main/src/groq/types/audio/transcription.py) documents only `text`. The implementation accepts a top-level `language` value when the provider actually supplies it and explicitly returns unknown otherwise. Mocked SDK tests verify parsing of that response shape; a live response still needs inspection before claiming reliable detection in production.

The shared registry's names and codes normalize to its ten canonical codes, including `Chinese`/`zh` → `zh-CN` and locale tags such as `hi-IN` → `hi`. Common additional provider source languages normalize to ISO-639-1 codes, for example `Italian` → `it`. These extra codes can be displayed as source metadata and passed as translation hints; they are not added as target selectors. Empty, malformed, or unrecognized labels become `null` and render as **Unknown language**. There is no invented confidence score. Detection is per completed phrase, not per word.

Manual source selection is kept as the effective translation hint even if the provider reports another language. The reported provider language is still shown as provider metadata. The LLM receives source metadata only as a structured hint; it is told to preserve code-switched words. Hindi-English and Marathi-English mixed speech is best effort.

## Automated checks

- Backend full isolated suite after the final REST failure-path regression: 241 passed, 2 skipped. One existing Starlette/httpx deprecation warning remains.
- Frontend: 115 passed; TypeScript and production build passed.
- Desktop bridge: 51 passed.
- All provider responses in automated tests are mocked. No live Groq call was made.
- One concurrent backend run had a timing-sensitive assertion measure 12 ms for a mocked 20 ms wait; the assertion was not weakened. The isolated full backend rerun passed.

## Manual browser verification

**NOT VERIFIED**: no real microphone or meeting-tab language-detection test was performed in this phase.

1. In Chrome or Edge, sign in and open `/microphone`. Leave the source at **Detect automatically**. Speak separate English, Hindi, and Marathi phrases; verify the original-caption label changes per phrase and the target stays selected.
2. Repeat on `/meeting` with user-authorized tab audio. Verify caption order and local target-language speech playback; audio is not broadcast to meeting participants.
3. Manually choose Hindi or Marathi as source, speak a short phrase, and confirm the selected source is sent as the STT hint. Switch languages only between sessions, as the current UI requires.
4. Try a same-language source and target; verify the original text is retained. Try short Hindi-English and Marathi-English code-switching and record transcription/translation errors without assuming word-level language accuracy.
5. Simulate a translation failure after STT and confirm the original caption remains while translated speech is not queued. Confirm pause, stop, mute, and reconnect still preserve order.

## Known limits and Phase 18 readiness

- Groq can omit or misidentify language metadata, especially on short or mixed-language phrases. Unknown metadata is explicit; no confidence value is exposed.
- Additional provider language names outside the bounded normalization map are shown as unknown, while their transcribed text can still be translated. Adding more target languages remains a separate task.
- Skipping an LLM call when a phrase is detected in the target language relies on phrase-level STT metadata. Code-switching inside that phrase can still need translation.
- Phase 17 implementation is ready for manual real-speech validation. Live detection and production readiness remain **NOT VERIFIED**; Phase 18 has not started.
