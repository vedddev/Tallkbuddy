# TalkBuddy desktop audio bridge — Phase 10D

This separate Windows command-line tool lists audio devices, plays existing PCM WAV files, captures phrases from an explicitly selected microphone, and can send those phrases to the authenticated TalkBuddy backend for translation and optional generated speech. Raw microphone audio is never sent to the virtual playback device or saved locally. The bridge does not join calls or change Windows defaults. The playback device for VB-CABLE routing is **CABLE Input**; **CABLE Output** is its recording side.

## Explicit microphone capture

List devices first. Choose the current numeric index of your physical microphone with `in=1` or greater. Indices can change after reboot or device reconnection. The listing includes host API and default sample rate.

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main devices
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main diagnose-mic --device MICROPHONE_INDEX
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main capture --device MICROPHONE_INDEX --duration 30 --diagnostics
```

`diagnose-mic` briefly opens only the selected input index. It reports the sounddevice and PortAudio versions, native sample rate, host API, tested channel/rate combinations, settings checks, actual stream-open results, callback frame counts, and numeric driver error codes. It does not save samples. A settings check alone cannot prove that a stream opens or delivers frames. Exit code 0 means at least one tested format delivered frames; 2 means none did. Choose another index explicitly if the same microphone appears under a different host API; the bridge never silently changes devices. For PortAudio `-9996` or `-9999`, check Windows microphone privacy, device availability, driver state, and exclusive-mode use.

Omit `--duration` to continue until Ctrl+C. `--diagnostics` prints audio level, speech/silence, phrase count, and dropped frames at most once per second. The command prints a completion summary and discards every emitted WAV after reporting metadata. It never falls back to the Windows default microphone. If Windows privacy settings block microphone access, enable microphone access for desktop apps and retry. If the stream disconnects, list devices again and choose its current index. `CABLE Output` is rejected unless `--allow-virtual-input` is also given; that flag is only for explicit virtual-source testing.

Optional segmentation controls: `--min-phrase 0.6`, `--max-phrase 12`, and `--silence 0.7` (seconds). The engine uses a lightweight adaptive RMS voice gate: 120 ms speech onset, 250 ms pre-speech padding, 700 ms end silence, at least 600 ms voiced speech, and 150 ms trailing padding. A phrase that exceeds the maximum without a brief silence is discarded to avoid an arbitrary mid-word cut; the summary counts these drops. Loud continuous background noise may prevent useful segmentation. This is an energy gate, not a trained speech detector.

PortAudio first probes the selected device's native sample rate and mono or stereo input capabilities with a short, input-only stream. It selects the first format that actually delivers frames. When stereo is required, it copies bounded callback blocks and downmixes to mono outside the audio callback. A bounded queue transfers blocks to the main thread; overflow resets the current phrase rather than emitting corrupted audio. Completed phrases become 16 kHz, mono, 16-bit PCM WAV bytes in memory. Each has a UUID, capture duration, and local monotonic speech-end and emission timestamps. No phrase audio or speech text appears in logs. Ctrl+C closes the input stream and clears queued data. The standalone `capture` command discards phrases and does not feed playback or loopback.

## Live translated speech into VB-CABLE (Phase 10D)

This mode starts only when you run `translate-live`. It prompts for your TalkBuddy email and password, uses the existing login endpoint, holds the HTTP-only session cookie in memory, and sends it only in the authenticated WebSocket handshake. The backend's Origin check remains active. Shutdown attempts to revoke the desktop session through the existing logout endpoint; if the backend is unreachable, that session expires under the backend's normal policy. Do not pass credentials in the command line, URL, or environment. Remote servers require HTTPS/WSS with normal TLS verification.

Configure Azure Speech on the **backend** in `backend/.env` with `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` for generated translated speech. The existing Groq key covers transcription and translation, but Groq/browser `speechSynthesis` does not supply a PCM WAV reply for desktop playback. Azure Speech is an additional paid provider; check its service availability and pricing before live use. Its output is requested as 24 kHz mono, 16-bit PCM WAV and resampled for the selected cable device. Start the backend using its usual command, then list the **current** device indices. Select a physical microphone for `--mic` and **CABLE Input** for `--output`:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m pip install -r .\desktop_bridge\requirements.txt
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main devices
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main translate-live --mic MIC_INDEX --output CABLE_INPUT_INDEX --source en --target hi --server http://127.0.0.1:8000 --diagnostics
```

Use `--source auto` (the default) for Whisper language detection. All ten codes in `shared/languages.json` are accepted by the translation service; speech output depends on the configured Azure resource and its voices. The command does not create a history record by default. To opt in, first enable history in your TalkBuddy preferences and create an owned translation session, then add `--save-history --session-id SESSION_UUID`. Phrase UUIDs are reused as request IDs for idempotent saving. Without both flags, saving stays off.

In a Windows terminal, press **P** to pause capture (frames are discarded locally), **R** to resume, **Q** or Ctrl+C to stop. The optional `--duration 30` stops capture after 30 seconds. Only **generated translated speech** is passed to CABLE Input. The bridge never sends raw microphone audio to the playback function. It processes one phrase at a time, keeps at most three pending phrases, and drops excess backlog rather than growing memory. After a long quiet interval or resume, it opens a fresh authenticated socket before sending another phrase; it never silently resubmits a phrase whose outcome is uncertain. A provider or connection failure stops the session; failed phrases are not automatically replayed. Device indices can change between runs. CABLE Output is selected as a microphone inside your calling application, never as `--output` here. Do not use CABLE Output as `--mic` because it creates a feedback path.

Diagnostics report local capture duration, speech-end to WebSocket submission, result round trip, server STT and translation durations, server TTS preparation, local playback queue wait, and speech-end to the call that starts virtual playback. They do not measure acoustic playback onset or remote participant hearing. Raw audio and recognized or translated words are not printed. This feature has not been verified in a live call merely by automated tests; manually check Windows CABLE Output activity and obtain remote-participant confirmation before claiming broadcast success.

## Setup in PowerShell

Run these commands from the TalkBuddy repository root with Python 3.11 or newer:

```powershell
py -3.11 -m venv .\desktop_bridge\.venv
.\desktop_bridge\.venv\Scripts\python.exe -m pip install -r .\desktop_bridge\requirements.txt
.\desktop_bridge\.venv\Scripts\python.exe -m pip install pytest
.\desktop_bridge\.venv\Scripts\python.exe -m pytest desktop_bridge\tests -q
```

Install VB-CABLE from the [official VB-Audio site](https://vb-audio.com/Cable/) if it is not already installed. Its Windows driver installer requires administrator approval and a reboot. The bridge never installs a driver or changes your default playback or recording device.

List all PortAudio devices and note the **index and host API** of `CABLE Input` and `CABLE Output`:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main devices
```

`CABLE Input` must show `out=1` or greater; `CABLE Output` must show `in=1` or greater. The listing also shows each device's default sample rate and host API. Several Windows host APIs can expose the same cable under different indices. If either side is missing, install or repair VB-CABLE, reboot if required, and list devices again. The bridge never changes Windows defaults.

Generate a quiet 2-second PCM test tone and play it into the cable. Replace `CABLE_INPUT_INDEX` with the `CABLE Input` playback index:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main test-wav .\desktop_bridge\test-tone.wav
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main play .\desktop_bridge\test-tone.wav --device CABLE_INPUT_INDEX
```

To play a spoken WAV file instead:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main play 'C:\path\to\spoken-test.wav' --device CABLE_INPUT_INDEX
```

Successful `play` waits until the WAV finishes and prints its duration. A failed device open or playback returns a nonzero exit code with an actionable message. `play` requires `--device` or an explicitly set `TALKBUDDY_BRIDGE_DEVICE`; there is no automatic device fallback. Prefer the numeric index because a name may match several host APIs. Optional limits: `TALKBUDDY_MAX_WAV_BYTES` (default 20 MiB) and `TALKBUDDY_MAX_WAV_SECONDS` (default 120). CLI `--device` takes precedence over the environment setting. Delete the test-tone WAV when finished.

## Optional local loopback check

Use a short spoken PCM WAV (five seconds or less). Choose the `CABLE Input` playback index and `CABLE Output` recording index, preferably under the same host API:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main verify-loopback 'C:\path\to\spoken-test.wav' --output CABLE_INPUT_INDEX --input CABLE_OUTPUT_INDEX
```

The command opens `CABLE Output` only after this explicit request, plays the WAV into `CABLE Input`, captures a bounded sample in memory, and prints baseline RMS, received RMS, peak, and captured duration. Exit code 0 means a local signal was detected; 2 means no clear signal was detected; 1 means a device or WAV error. It never saves the recording. This proves only the local cable path, **not** that a calling application received or transmitted audio. If the recording stream cannot open, check Windows microphone privacy permissions, app exclusive-mode use, and whether the selected indices still exist; try another matching host-API pair in an interactive desktop session. A tone may be suppressed by calling apps, so use speech for their manual test.

## Configure calling applications

Select **CABLE Output (VB-Audio Virtual Cable)** as the microphone or input device in each application:

| Application | Where to select it |
| --- | --- |
| Google Meet | Settings → Audio → Microphone |
| Zoom | Settings → Audio → Microphone |
| Discord | User Settings → Voice & Video → Input Device |
| Microsoft Teams | Settings → Devices → Microphone |

Then play a short spoken WAV into **CABLE Input** using the explicit `play` command above. Check the app's input meter and, with consent, ask a remote participant whether they hear it. Restore your normal microphone in each application's same menu after testing. App noise suppression, automatic gain control, and other microphone processing can change or suppress what participants hear. Use headphones to avoid feedback.

## Verify routing in Google Meet

1. With VB-CABLE installed, open Google Meet's **Settings → Audio → Microphone** and select **CABLE Output (VB-Audio Virtual Cable)**. Do not select `CABLE Input` as the microphone.
2. Start or join a call with a consenting remote participant. Play a short **spoken** PCM WAV into `CABLE Input` using the command above. Meet may suppress a steady test tone as background noise, so speech is the better end-to-end test.
3. Check Meet's microphone activity indicator and ask the remote participant whether they heard the spoken test clearly. Restore your normal microphone in Meet when finished.

This manual call is required to verify broadcasting. The tool cannot confirm remote audibility by itself. Selecting `CABLE Output` in Meet affects that Meet session's microphone setting; the bridge does not edit Windows defaults. Use headphones to prevent feedback. Do not run a meeting capture or transmit audio without participant permission.

## Audio compatibility and limits

The bridge accepts uncompressed integer PCM WAV at 8, 16, 24, or 32 bits, 1–8 input channels, and 8–192 kHz. It converts samples to float32, downmixes or duplicates channels for a mono/stereo output, and uses linear interpolation when the selected device needs another sample rate. It probes the device format before playback and reports unavailable or incompatible devices. Floating-point WAV, compressed WAV, and WAVE_FORMAT_EXTENSIBLE files unsupported by Python's `wave` reader need conversion to standard PCM first. Linear resampling is adequate for a routing test but is not a high-quality production speech resampler.

The [shared language registry](../shared/languages.json) contains ten canonical codes and separate Groq Whisper hints and browser speech tags. FastAPI now accepts all ten codes. Browser voice availability still depends on installed voices, and this bridge remains a standalone WAV playback and local loopback check tool. It has no live TTS-to-cable pipeline.
