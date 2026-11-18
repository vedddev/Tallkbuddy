"""Command-line playback bridge for a user-selected Windows virtual cable."""

import argparse
import sys

from desktop_bridge.audio_devices import DeviceError, format_device, list_devices, select_output_device
from desktop_bridge.config import BridgeConfig
from desktop_bridge.wav_player import PlaybackError, WavError, play_wav, write_test_wav


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TalkBuddy Windows WAV-to-virtual-microphone bridge")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List playback and recording devices")
    play = commands.add_parser("play", help="Play a PCM WAV into a selected playback output")
    play.add_argument("file", help="Path to a PCM WAV file")
    play.add_argument("--device", help="Playback device index or name; defaults to a unique CABLE Input")
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
            return 0
        output = select_output_device(devices, args.device or config.preferred_device)
        print(f"Playing to device {output.index}: {output.name}")
        audio = play_wav(args.file, output, config)
        print(f"Finished {audio.duration_seconds:.2f} seconds of WAV playback.")
        return 0
    except (DeviceError, PlaybackError, WavError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
