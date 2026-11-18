# TalkBuddy desktop audio bridge — Phase 10B

This separate Windows command-line tool lists audio devices and plays an existing, uncompressed integer PCM WAV file into a selected playback device. It does not capture meeting audio, synthesize speech, call Groq, join Google Meet, or change Windows default devices. The intended playback device is **CABLE Input** (the playback side of VB-CABLE). Google Meet must use **CABLE Output** (the recording side) as its microphone. VB-Audio describes this direction in its [VB-CABLE reference manual](https://vb-audio.com/Cable/VBCABLE_ReferenceManual.pdf).

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
