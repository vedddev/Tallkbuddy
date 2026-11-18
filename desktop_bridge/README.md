# TalkBuddy desktop audio bridge — Phase 9A

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

List all PortAudio devices and note the **index** of `CABLE Input` and `CABLE Output`:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main devices
```

`CABLE Input` must show `out=1` or greater; `CABLE Output` must show `in=1` or greater. Several Windows host APIs can expose the same cable under different indices. The bridge refuses an ambiguous automatic match; use the intended playback index shown by `devices`.

Generate a quiet 2-second PCM test tone and play it into the cable. Replace `DEVICE_INDEX` with the `CABLE Input` playback index:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main test-wav .\desktop_bridge\test-tone.wav
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main play .\desktop_bridge\test-tone.wav --device DEVICE_INDEX
```

To play a spoken WAV file instead:

```powershell
.\desktop_bridge\.venv\Scripts\python.exe -m desktop_bridge.main play 'C:\path\to\spoken-test.wav' --device DEVICE_INDEX
```

With exactly one detected `CABLE Input`, `--device` may be omitted. To choose by name, use `--device 'CABLE Input'` if it matches only one output. The bridge never silently routes to regular speakers. Optional configuration: `TALKBUDDY_BRIDGE_DEVICE` (index or name), `TALKBUDDY_MAX_WAV_BYTES` (default 20 MiB), and `TALKBUDDY_MAX_WAV_SECONDS` (default 120). CLI `--device` takes precedence over the environment setting.

## Verify routing in Google Meet

1. With VB-CABLE installed, open Google Meet's **Settings → Audio → Microphone** and select **CABLE Output (VB-Audio Virtual Cable)**. Do not select `CABLE Input` as the microphone.
2. Start or join a call with a consenting remote participant. Play a short **spoken** PCM WAV into `CABLE Input` using the command above. Meet may suppress a steady test tone as background noise, so speech is the better end-to-end test.
3. Check Meet's microphone activity indicator and ask the remote participant whether they heard the spoken test clearly. Restore your normal microphone in Meet when finished.

This manual call is required to verify broadcasting. The tool cannot confirm remote audibility by itself. Selecting `CABLE Output` in Meet affects that Meet session's microphone setting; the bridge does not edit Windows defaults. Use headphones to prevent feedback. Do not run a meeting capture or transmit audio without participant permission.

## Audio compatibility and limits

The bridge accepts uncompressed integer PCM WAV at 8, 16, 24, or 32 bits, 1–8 input channels, and 8–192 kHz. It converts samples to float32, downmixes or duplicates channels for a mono/stereo output, and uses linear interpolation when the selected device needs another sample rate. It probes the device format before playback and reports unavailable or incompatible devices. Floating-point WAV, compressed WAV, and WAVE_FORMAT_EXTENSIBLE files unsupported by Python's `wave` reader need conversion to standard PCM first. Linear resampling is adequate for a routing test but is not a high-quality production speech resampler.

The [shared language registry](../shared/languages.json) contains ten canonical codes and separate Groq Whisper hints and browser speech tags. FastAPI now accepts all ten codes. Browser voice availability still depends on installed voices, and this bridge remains a standalone WAV playback tool. It has no live TTS-to-cable pipeline.
