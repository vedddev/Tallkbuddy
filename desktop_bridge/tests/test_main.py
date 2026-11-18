from types import SimpleNamespace

import pytest

from desktop_bridge.audio_devices import AudioDevice
from desktop_bridge.loopback import LoopbackResult
from desktop_bridge.main import main


SPEAKER = AudioDevice(0, "Speakers", 0, 2, 48000, "Windows WASAPI")
CABLE_IN = AudioDevice(4, "CABLE Input", 0, 2, 48000, "Windows WASAPI")
CABLE_OUT = AudioDevice(5, "CABLE Output", 2, 0, 48000, "Windows WASAPI")


def test_devices_reports_capabilities_and_missing_cable(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("desktop_bridge.main.list_devices", lambda: [SPEAKER])
    assert main(["devices"]) == 1
    output = capsys.readouterr()
    assert "host=Windows WASAPI" in output.out
    assert "Install VB-CABLE" in output.err


def test_play_requires_explicit_device_and_confirms_blocking_completion(
    monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    monkeypatch.delenv("TALKBUDDY_BRIDGE_DEVICE", raising=False)
    monkeypatch.setattr("desktop_bridge.main.list_devices", lambda: [SPEAKER, CABLE_IN, CABLE_OUT])
    played = []
    monkeypatch.setattr(
        "desktop_bridge.main.play_wav",
        lambda path, device, config: played.append((path, device)) or SimpleNamespace(duration_seconds=0.5),
    )
    assert main(["play", "speech.wav"]) == 1
    assert "Select CABLE Input explicitly" in capsys.readouterr().err
    assert not played
    assert main(["play", "speech.wav", "--device", "4"]) == 0
    assert played == [("speech.wav", CABLE_IN)]
    assert "Finished 0.50 seconds" in capsys.readouterr().out


def test_loopback_command_requires_both_cable_sides_and_reports_local_only(
    monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    monkeypatch.setattr("desktop_bridge.main.list_devices", lambda: [SPEAKER, CABLE_IN, CABLE_OUT])
    called = []
    monkeypatch.setattr(
        "desktop_bridge.main.verify_loopback",
        lambda path, output, recording, config: called.append((path, output, recording)) or
        LoopbackResult(True, 0.0, 0.05, 0.2, 0.5),
    )
    assert main(["verify-loopback", "speech.wav", "--output", "4", "--input", "5"]) == 0
    assert called == [("speech.wav", CABLE_IN, CABLE_OUT)]
    assert "does not prove a calling app" in capsys.readouterr().out
    assert main(["verify-loopback", "speech.wav", "--output", "0", "--input", "5"]) == 1
    assert "CABLE Input" in capsys.readouterr().err
    monkeypatch.setattr(
        "desktop_bridge.main.verify_loopback",
        lambda *_args: LoopbackResult(False, 0.0, 0.0, 0.0, 0.5),
    )
    assert main(["verify-loopback", "speech.wav", "--output", "4", "--input", "5"]) == 2
    assert "no clear signal detected" in capsys.readouterr().out
