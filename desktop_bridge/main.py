"""Command-line playback bridge for a user-selected Windows virtual cable."""

import argparse
import os
import sys

from desktop_bridge.audio_devices import (
    DeviceError, format_device, list_devices, select_input_device, select_output_device, sounddevice_backend,
)
from desktop_bridge.config import BridgeConfig
from desktop_bridge.loopback import LoopbackError, verify_loopback
from desktop_bridge.microphone import CaptureConfig, CaptureError, capture_microphone
from desktop_bridge.mic_diagnostics import format_probe, probe_input_formats
from desktop_bridge.wav_player import PlaybackError, WavError, play_wav, write_test_wav


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TalkBuddy Windows WAV-to-virtual-microphone bridge")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List playback and recording devices")
    play = commands.add_parser("play", help="Play a PCM WAV into a selected playback output")
    play.add_argument("file", help="Path to a PCM WAV file")
    play.add_argument("--device", help="Explicit playback device index or name (CABLE Input)")
    loopback = commands.add_parser("verify-loopback", help="Locally check CABLE Input to CABLE Output routing")
    loopback.add_argument("file", help="Spoken PCM WAV file, at most 5 seconds")
    loopback.add_argument("--output", required=True, help="CABLE Input playback device index")
    loopback.add_argument("--input", required=True, help="CABLE Output recording device index")
    tone = commands.add_parser("test-wav", help="Create a quiet PCM test tone WAV file")
    tone.add_argument("file", help="Output WAV path")
    capture = commands.add_parser("capture", help="Capture spoken phrases from an explicitly selected microphone")
    capture.add_argument("--device", required=True, help="Microphone input device index from 'devices'")
    capture.add_argument("--duration", type=float, help="Stop automatically after this many seconds (maximum 3600)")
    capture.add_argument("--diagnostics", action="store_true", help="Show audio level and speech status once per second")
    capture.add_argument("--min-phrase", type=float, default=0.6, help="Minimum voiced speech seconds (default 0.6)")
    capture.add_argument("--max-phrase", type=float, default=12.0, help="Maximum phrase seconds (default 12)")
    capture.add_argument("--silence", type=float, default=0.7, help="Silence seconds to finish a phrase (default 0.7)")
    capture.add_argument("--allow-virtual-input", action="store_true", help="Explicitly allow recording CABLE Output")
    diagnose = commands.add_parser("diagnose-mic", help="Probe one explicitly selected input without storing audio")
    diagnose.add_argument("--device", required=True, help="Current microphone input index from 'devices'")
    diagnose.add_argument("--allow-virtual-input", action="store_true", help="Explicitly probe CABLE Output")
    live = commands.add_parser("translate-live", help="Translate a physical microphone into CABLE Input with opt-in speech audio")
    live.add_argument("--mic", required=True, help="Current physical microphone input index")
    live.add_argument("--output", required=True, help="Current CABLE Input playback index")
    live.add_argument("--source", default="auto", help="Source code or auto (default auto)")
    live.add_argument("--target", required=True, help="Target language code")
    live.add_argument("--server", default=os.getenv("TALKBUDDY_SERVER", "http://127.0.0.1:8000"), help="Backend origin")
    live.add_argument("--diagnostics", action="store_true", help="Show stage timings without speech content")
    live.add_argument("--duration", type=float, help="Optional capture duration in seconds")
    live.add_argument("--save-history", action="store_true", help="Explicitly save results to an existing owned session")
    live.add_argument("--session-id", help="Existing owned session UUID; requires --save-history")
    args = parser.parse_args(argv)

    try:
        if args.command == "test-wav":
            write_test_wav(args.file)
            print(f"Wrote test WAV: {args.file}")
            return 0
        devices = list_devices()
        if args.command == "devices":
            if not devices:
                raise DeviceError("No Windows audio devices were found.")
            for device in devices:
                print(format_device(device))
            if not any(device.cable_input for device in devices) or not any(device.cable_output for device in devices):
                raise DeviceError(
                    "VB-CABLE Input/Output pair was not found. Install VB-CABLE from vb-audio.com/Cable/, "
                    "reboot if required, then run 'devices' again."
                )
            return 0
        if args.command == "diagnose-mic":
            if not args.device.strip().isdigit():
                raise DeviceError("Choose a numeric input index from 'devices'.")
            microphone = select_input_device(devices, args.device)
            if microphone.cable_output and not args.allow_virtual_input:
                raise DeviceError("CABLE Output is a virtual input; add --allow-virtual-input to probe it explicitly.")
            backend = sounddevice_backend()
            print(format_device(microphone))
            print(f"sounddevice={backend.__version__}; PortAudio={backend.get_portaudio_version()[1]}")
            probes = probe_input_formats(microphone, backend=backend)
            for probe in probes:
                print(format_probe(probe))
            usable = [probe for probe in probes if probe.usable]
            if usable:
                first = usable[0]
                print(f"Usable selected-device configuration: {first.sample_rate} Hz, {first.channels} channel(s). "
                      "Capture converts to 16 kHz mono after input.")
                return 0
            print("No tested format delivered frames. Check Windows microphone privacy, exclusive mode, "
                  "driver availability, and another explicit host-API entry for this microphone.")
            return 2
        if args.command == "capture":
            if not args.device.strip().isdigit():
                raise DeviceError("Choose a microphone by numeric index from 'devices'; no default input is used.")
            microphone = select_input_device(devices, args.device)
            if microphone.cable_output and not args.allow_virtual_input:
                raise DeviceError("CABLE Output is a virtual input. Add --allow-virtual-input only if you intend to capture it.")
            capture_config = CaptureConfig(
                min_speech_seconds=args.min_phrase, max_phrase_seconds=args.max_phrase,
                silence_seconds=args.silence,
            )
            summary = capture_microphone(
                microphone, lambda _phrase: None, duration=args.duration,
                diagnostics=args.diagnostics, config=capture_config,
            )
            print(f"Capture finished: {summary.phrases} phrases, {summary.dropped_frames} dropped frames, "
                  f"{summary.dropped_long_phrases} overlong phrases discarded, {summary.elapsed_seconds:.1f}s elapsed. "
                  "No audio was saved or sent.")
            return 0
        if args.command == "translate-live":
            try:
                from desktop_bridge.live_client import LiveClientError
                from desktop_bridge.live_translate import run_live, select_live_devices
                microphone, output = select_live_devices(args.mic, args.output, devices)
                return run_live(microphone, output, args.source, args.target, args.server,
                                diagnostics=args.diagnostics, save_history=args.save_history,
                                session_id=args.session_id, duration=args.duration)
            except ImportError as exc:
                print("Error: Live client dependencies are missing. Install desktop_bridge/requirements.txt.", file=sys.stderr)
                return 1
            except LiveClientError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
        config = BridgeConfig.from_environment()
        if args.command == "verify-loopback":
            output = select_output_device(devices, args.output)
            recording = select_input_device(devices, args.input)
            if not output.cable_input:
                raise DeviceError("Loopback output must be CABLE Input, not a physical speaker.")
            if not recording.cable_output:
                raise DeviceError("Loopback recording source must be CABLE Output.")
            result = verify_loopback(args.file, output, recording, config)
            print(
                f"Local CABLE Output check: {'signal detected' if result.detected else 'no clear signal detected'}; "
                f"RMS={result.received_rms:.5f}, peak={result.received_peak:.5f}, "
                f"baseline RMS={result.baseline_rms:.5f}, captured={result.recorded_seconds:.2f} s."
            )
            print("This checks the local cable path only; it does not prove a calling app or remote participant received audio.")
            return 0 if result.detected else 2
        selector = args.device or config.preferred_device
        if not selector:
            raise DeviceError("Select CABLE Input explicitly with --device INDEX (or TALKBUDDY_BRIDGE_DEVICE). Run 'devices' first.")
        output = select_output_device(devices, selector)
        print(f"Playing to device {output.index}: {output.name}")
        audio = play_wav(args.file, output, config)
        print(f"Finished {audio.duration_seconds:.2f} seconds of WAV playback.")
        return 0
    except (DeviceError, CaptureError, LoopbackError, PlaybackError, WavError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped by Ctrl+C.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
