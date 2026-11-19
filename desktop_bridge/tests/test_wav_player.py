from pathlib import Path
import wave

import numpy as np
import pytest

from desktop_bridge.audio_devices import AudioDevice
from desktop_bridge.config import BridgeConfig
from desktop_bridge.wav_player import (
    PlaybackError,
    WavError,
    adapt_channels,
    load_pcm_wav,
    play_wav,
    play_wav_bytes,
    resample_audio,
    write_test_wav,
)


def make_wav(path: Path, width: int, channels: int, frames: list[int], rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        if width == 1:
            writer.writeframes(bytes(frames))
        else:
            writer.writeframes(b"".join(value.to_bytes(width, "little", signed=True) for value in frames))


@pytest.mark.parametrize(
    "width,values",
    [(1, [0, 128, 255]), (2, [-32768, 0, 32767]), (3, [-8388608, 0, 8388607]), (4, [-2147483648, 0, 2147483647])],
)
def test_decodes_integer_pcm_widths(tmp_path: Path, width: int, values: list[int]) -> None:
    path = tmp_path / f"pcm{width}.wav"
    make_wav(path, width, 1, values)
    audio = load_pcm_wav(path)
    assert audio.samples.shape == (3, 1)
    assert audio.samples.dtype == np.float32
    assert audio.samples[0, 0] == pytest.approx(-1)
    assert audio.samples[1, 0] == pytest.approx(0)
    assert audio.samples[2, 0] > 0.99


def test_resamples_and_adapts_stereo_or_mono() -> None:
    stereo = np.array([[1, -1], [0.5, -0.5], [0, 0]], dtype=np.float32)
    mono = adapt_channels(stereo, 1)
    assert mono.shape == (3, 1)
    assert np.allclose(mono, 0)
    doubled = adapt_channels(mono, 2)
    assert doubled.shape == (3, 2)
    assert resample_audio(stereo, 16000, 48000).shape == (9, 2)


class FakePlaybackBackend:
    def __init__(self):
        self.calls = []
        self.played = None

    def check_output_settings(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["samplerate"] != 48000:
            raise RuntimeError("rate unavailable")

    def play(self, data, **kwargs):
        self.played = (data, kwargs)


def test_plays_to_explicit_cable_input_with_rate_conversion(tmp_path: Path) -> None:
    path = tmp_path / "speech.wav"
    make_wav(path, 2, 1, [0, 1000, -1000, 0] * 100, rate=16000)
    cable = AudioDevice(7, "CABLE Input", 0, 2, 48000)
    backend = FakePlaybackBackend()
    audio = play_wav(path, cable, backend=backend)
    data, options = backend.played
    assert audio.sample_rate == 16000
    assert data.shape == (1200, 2)
    assert options == {"samplerate": 48000, "device": 7, "blocking": True}
    assert backend.calls[0]["device"] == 7


def test_plays_in_memory_24khz_speech_wav_to_cable_at_48khz(tmp_path: Path) -> None:
    path = tmp_path / "generated.wav"
    make_wav(path, 2, 1, [0, 1000, -1000, 0] * 100, rate=24000)
    backend = FakePlaybackBackend()
    cable = AudioDevice(14, "CABLE Input", 0, 2, 48000)
    audio = play_wav_bytes(path.read_bytes(), cable, backend=backend)
    assert audio.sample_rate == 24000
    data, options = backend.played
    assert data.shape == (800, 2)
    assert options["device"] == 14


def test_rejects_recording_device_and_oversized_wav(tmp_path: Path) -> None:
    path = tmp_path / "small.wav"
    write_test_wav(path, seconds=0.1)
    recording_side = AudioDevice(8, "CABLE Output", 2, 0, 48000)
    with pytest.raises(PlaybackError, match="not a playback output"):
        play_wav(path, recording_side, backend=FakePlaybackBackend())
    with pytest.raises(WavError, match="size limit"):
        load_pcm_wav(path, BridgeConfig(max_wav_bytes=100))


def test_test_tone_is_valid_pcm_wav(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    write_test_wav(path)
    audio = load_pcm_wav(path)
    assert audio.sample_rate == 48000
    assert audio.samples.shape == (96000, 1)
    assert audio.samples.max() < 0.13


def test_invalid_wav_and_unavailable_output_are_reported(tmp_path: Path) -> None:
    invalid = tmp_path / "broken.wav"
    invalid.write_bytes(b"not a WAV")
    with pytest.raises(WavError, match="Invalid or unsupported WAV"):
        load_pcm_wav(invalid)
    valid = tmp_path / "valid.wav"
    make_wav(valid, 2, 1, [0, 1000, -1000])
    cable = AudioDevice(3, "CABLE Input", 0, 2, 48000)
    class UnavailableBackend:
        def check_output_settings(self, **_kwargs):
            raise RuntimeError("unavailable")
    with pytest.raises(PlaybackError, match="No compatible sample rate"):
        play_wav(valid, cable, backend=UnavailableBackend())


def test_playback_failure_stops_the_device_and_hides_driver_details(tmp_path: Path) -> None:
    path = tmp_path / "spoken.wav"
    make_wav(path, 2, 1, [1000, -1000] * 200)
    class FailingBackend:
        stopped = False
        def check_output_settings(self, **_kwargs):
            pass
        def play(self, *_args, **_kwargs):
            raise RuntimeError("private driver detail")
        def stop(self):
            self.stopped = True
    backend = FailingBackend()
    with pytest.raises(PlaybackError, match="Audio playback failed") as failure:
        play_wav(path, AudioDevice(7, "CABLE Input", 0, 2, 48000), backend=backend)
    assert "private driver detail" not in str(failure.value)
    assert backend.stopped
