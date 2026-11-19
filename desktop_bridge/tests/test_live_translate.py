from threading import Event
import time

import numpy as np
import pytest

from desktop_bridge.audio_devices import AudioDevice
from desktop_bridge.live_client import SpeechResponse
from desktop_bridge.live_translate import run_live
from desktop_bridge.microphone import CaptureError, CaptureSummary, encode_phrase


MIC = AudioDevice(18, "Physical microphone", 2, 0, 48000)
CABLE = AudioDevice(14, "CABLE Input", 0, 2, 48000)


def test_only_generated_speech_reaches_virtual_output_and_resources_close(monkeypatch) -> None:
    phrase = encode_phrase(np.ones(1600, dtype=np.float32) * 0.1, 16000, time.perf_counter() * 1000)
    generated = b"generated-voice-placeholder"
    played = []
    closed = []

    class FakeCookies:
        def get(self, name):
            return "session" if name == "talkbuddy_session" else None

    class FakeClient:
        cookies = FakeCookies()

        def close(self):
            closed.append("client")

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_):
            closed.append("socket")

        def translate(self, incoming):
            assert incoming.wav_bytes == phrase.wav_bytes
            return SpeechResponse(1, "private", "private", generated, time.perf_counter() * 1000,
                                  100, 40, 30, 20, time.perf_counter() * 1000)

    def capture(_mic, on_phrase, **kwargs):
        assert isinstance(kwargs["stop_event"], Event)
        on_phrase(phrase)
        return CaptureSummary(1, 0, 0, 0.1)

    monkeypatch.setattr("builtins.input", lambda _: "user@example.com")
    monkeypatch.setattr("desktop_bridge.live_translate.getpass", lambda _: "private-password")
    monkeypatch.setattr("desktop_bridge.live_translate.login", lambda *a, **kw: FakeClient())
    monkeypatch.setattr("desktop_bridge.live_translate.logout", lambda *a: closed.append("logout"))
    monkeypatch.setattr("desktop_bridge.live_translate.TranslationConnection", FakeConnection)
    monkeypatch.setattr("desktop_bridge.live_translate.capture_microphone", capture)
    monkeypatch.setattr("desktop_bridge.live_translate.play_wav_bytes", lambda audio, device: played.append((audio, device)))
    monkeypatch.setattr("desktop_bridge.live_translate._keyboard_action", lambda: None)
    assert run_live(MIC, CABLE, "en", "hi", "http://127.0.0.1:8000", report=lambda _: None) == 0
    assert played == [(generated, CABLE)]
    assert "socket" in closed and "logout" in closed and "client" in closed


def test_invalid_live_device_rejected_before_credentials(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompt must not run"))
    with pytest.raises(Exception, match="physical microphone"):
        run_live(AudioDevice(17, "CABLE Output", 2, 0, 48000), CABLE,
                 "en", "hi", "http://127.0.0.1:8000")


def test_capture_failure_closes_socket_and_revokes_login(monkeypatch) -> None:
    closed = []

    class FakeClient:
        cookies = type("Cookies", (), {"get": lambda self, _: "session"})()

        def close(self):
            closed.append("client")

    class FakeConnection:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            closed.append("socket")

    def fail_capture(*_, **__):
        raise CaptureError("device unavailable")

    monkeypatch.setattr("builtins.input", lambda _: "user@example.com")
    monkeypatch.setattr("desktop_bridge.live_translate.getpass", lambda _: "private-password")
    monkeypatch.setattr("desktop_bridge.live_translate.login", lambda *a, **kw: FakeClient())
    monkeypatch.setattr("desktop_bridge.live_translate.logout", lambda *a: closed.append("logout"))
    monkeypatch.setattr("desktop_bridge.live_translate.TranslationConnection", FakeConnection)
    monkeypatch.setattr("desktop_bridge.live_translate.capture_microphone", fail_capture)
    monkeypatch.setattr("desktop_bridge.live_translate._keyboard_action", lambda: None)
    with pytest.raises(CaptureError, match="device error"):
        run_live(MIC, CABLE, "en", "hi", "http://127.0.0.1:8000", report=lambda _: None)
    assert closed == ["socket", "logout", "client"]
