"""Command-line playback bridge for a user-selected Windows virtual cable."""

import argparse
import sys

from desktop_bridge.audio_devices import (
    DeviceError, format_device, list_devices, select_input_device, select_output_device,
)
from desktop_bridge.config import BridgeConfig
from desktop_bridge.loopback import LoopbackError, verify_loopback
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
    args = parser.parse_args(argv)

    try:
        config = BridgeConfig.from_environment()
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
    except (DeviceError, LoopbackError, PlaybackError, WavError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
