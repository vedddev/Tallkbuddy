from pathlib import Path

import numpy as np
import pytest

from desktop_bridge.audio_devices import AudioDevice, DeviceError
from desktop_bridge.loopback import LoopbackError, verify_loopback
from desktop_bridge.wav_player import PlaybackError, WavError, write_test_wav


OUTPUT = AudioDevice(4, "CABLE Input (VB-Audio Virtual Cable)", 0, 2, 48000)
INPUT = AudioDevice(5, "CABLE Output (VB-Audio Virtual Cable)", 2, 0, 48000)


class FakeBackend:
    def __init__(self, echo: bool = True, fail_playback: bool = False):
        self.echo = echo
        self.fail_playback = fail_playback
        self.callback = None
        self.stream_closed = False
        self.stopped = False

    def check_input_settings(self, **kwargs):
        assert kwargs["device"] == INPUT.index

    def check_output_settings(self, **kwargs):
        assert kwargs["device"] == OUTPUT.index

    def InputStream(self, **kwargs):
        self.callback = kwargs["callback"]
        outer = self
        class Stream:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                outer.stream_closed = True
        return Stream()

    def sleep(self, milliseconds: int):
        assert self.callback is not None
        self.callback(np.zeros((milliseconds * 48, 2), dtype=np.float32), milliseconds * 48, None, None)

    def play(self, data, **kwargs):
        assert kwargs == {"samplerate": 48000, "device": OUTPUT.index, "blocking": True}
        if self.fail_playback:
            raise RuntimeError("driver unavailable")
        if self.echo:
            assert self.callback is not None
            self.callback(data, data.shape[0], None, None)

    def stop(self):
        self.stopped = True


def test_local_loopback_detects_audio_and_closes_resources(tmp_path: Path) -> None:
    path = tmp_path / "spoken.wav"
    write_test_wav(path, seconds=0.5)
    backend = FakeBackend()
    result = verify_loopback(path, OUTPUT, INPUT, backend=backend)
    assert result.detected
    assert result.baseline_rms == 0
    assert result.received_rms > 0.003
    assert result.recorded_seconds <= 1.5
    assert backend.stream_closed and backend.stopped
    assert not list(tmp_path.glob("*.raw"))


def test_no_signal_is_reported_without_false_success(tmp_path: Path) -> None:
    path = tmp_path / "spoken.wav"
    write_test_wav(path, seconds=0.2)
    result = verify_loopback(path, OUTPUT, INPUT, backend=FakeBackend(echo=False))
    assert not result.detected
    assert result.received_peak == 0


def test_loopback_rejects_wrong_cable_sides_and_long_audio(tmp_path: Path) -> None:
    path = tmp_path / "spoken.wav"
    write_test_wav(path, seconds=0.2)
    with pytest.raises(DeviceError, match="CABLE Input"):
        verify_loopback(path, AudioDevice(1, "Speakers", 0, 2, 48000), INPUT, backend=FakeBackend())
    with pytest.raises(DeviceError, match="CABLE Output"):
        verify_loopback(path, OUTPUT, AudioDevice(2, "Microphone", 2, 0, 48000), backend=FakeBackend())
    write_test_wav(path, seconds=5.1)
    with pytest.raises(WavError, match="5 seconds"):
        verify_loopback(path, OUTPUT, INPUT, backend=FakeBackend())


def test_input_failure_or_playback_error_closes_stream(tmp_path: Path) -> None:
    path = tmp_path / "spoken.wav"
    write_test_wav(path, seconds=0.2)
    class InvalidInput(FakeBackend):
        def check_input_settings(self, **_kwargs):
            raise RuntimeError("unavailable")
    with pytest.raises(LoopbackError, match="cannot record"):
        verify_loopback(path, OUTPUT, INPUT, backend=InvalidInput())
    backend = FakeBackend(fail_playback=True)
    with pytest.raises(PlaybackError, match="Audio playback failed"):
        verify_loopback(path, OUTPUT, INPUT, backend=backend)
    assert backend.stream_closed and backend.stopped
