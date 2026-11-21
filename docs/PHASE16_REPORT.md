# Phase 16: Azure TTS and automatic speech fallback

## Implemented

- Existing authenticated `/ws/translate` contract remains in use. The browser requests optional `synthesize_speech`; if Azure is disabled, it resends `start` without speech on the same authenticated socket and keeps captions flowing.
- Azure is **disabled by default**. `AZURE_TTS_ENABLED=true` is required in addition to a private key, region, and HTTPS Azure Speech resource endpoint. This is an explicit billing gate; this phase made no live Azure requests.
- When enabled, the backend discovers the resource's currently available neural voices, selects an exact locale match for the target language, and prefers the existing Hindi `hi-IN-SwaraNeural` and Marathi `mr-IN-AarohiNeural` names when present. The catalog is cached for one hour. Azure errors and timeouts are categorized without logging keys, response bodies, or translated text.
- Browser playback uses one bounded, ordered coordinator. A failed Azure phrase tries a matching installed browser voice. If no matching voice exists, captions remain visible. A generated phrase that has already started is never replayed as browser speech. Pause, mute, stop, and reconnect clear or suspend playback through the existing session controls.
- The Live Meeting and Microphone workspaces display the provider only after actual Azure `onplaying` or browser `onstart` events; missing voices and fallback are reported in text.

## Files changed for Phase 16

- `backend/.env.example`, `backend/app/core/config.py`, `backend/app/ai/tts.py`, `backend/tests/test_tts.py`, `backend/tests/test_websocket.py`, `backend/README.md`
- `frontend/src/lib/autoSpeechQueue.ts`, `frontend/src/lib/speechQueue.ts`, `frontend/src/lib/generatedSpeechQueue.ts`, `frontend/src/lib/socket.ts`, `frontend/src/components/MeetingInterpreter.tsx`, `frontend/src/test/autoSpeechQueue.test.ts`, `frontend/src/test/socket.test.ts`, `frontend/src/test/meetingInterpreter.test.tsx`, `frontend/README.md`
- This report. Other modified files in the working tree belong to preceding phases and were preserved.

## Configuration

Leave `AZURE_TTS_ENABLED=false` for browser voice and captions only. If Azure usage is separately approved, place these settings in the private `backend/.env`:

```dotenv
AZURE_TTS_ENABLED=true
AZURE_SPEECH_KEY=<private Azure Speech key>
AZURE_SPEECH_REGION=<resource region>
AZURE_SPEECH_ENDPOINT=https://<resource-name>.cognitiveservices.azure.com
```

Do not put the key in Vite environment variables or source control. The endpoint must be the HTTPS Azure resource origin. The backend obtains the catalog from Azure's [voice listing API](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech). Microsoft lists [Hindi and Marathi neural voices](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=text-to-speech), but availability and playback must be checked on the actual resource and browser. Restart the backend after changing settings.

## Automated verification

- Backend full suite: 222 passed, 2 skipped; one existing Starlette/httpx deprecation warning. After the final endpoint validation edit, focused Azure and WebSocket suites passed separately (16 and 38 tests).
- Frontend full suite: 114 passed. The final focused fallback/UI run passed 14 tests; the last late-audio guard passed its 3 focused tests.
- Desktop bridge: 51 passed.
- TypeScript: passed. Frontend production build: passed.
- Provider calls in tests use mocks. No billable Azure request was made.

## Manual verification checklist

Status: **NOT VERIFIED**. A real browser, installed voices, Azure credentials, and approved Azure usage were not available for this check.

1. With Azure disabled, sign in, open `/microphone`, select Hindi, speak a short English phrase, and confirm Hindi captions. Check whether an installed Hindi browser voice starts; otherwise confirm the captions-only warning.
2. Repeat with Marathi and verify the selected browser voice has a Marathi language tag. No unrelated language voice should speak.
3. Pause, resume, mute, and stop while phrases are pending. Confirm no overlapping or stale speech.
4. After separately approving Azure usage and configuring it privately, repeat both languages. Confirm Azure `speech_audio`, actual `onplaying`, and provider indicator. Simulate an Azure failure and confirm a matching browser voice or captions-only fallback.
5. Deny browser autoplay, disconnect the WebSocket, and reconnect. Confirm captions remain and no phrase is replayed twice.

## Limits and next-phase readiness

- Browser voice presence varies by OS and installed language packs. Azure voice discovery confirms a configured resource catalog, not that generated audio reached speakers.
- Azure voice discovery adds a provider request on first use per process; synthesis and network latency remain unmeasured here.
- The WebSocket protocol still serializes phrase processing and does not guarantee exactly-once delivery after disconnection.
- Phase 16 is implemented and automatically tested. Real Hindi and Marathi playback is **NOT VERIFIED**, so any release gate requiring audible language verification remains open. No next phase was started.
