from io import BytesIO
import wave

import numpy as np
import pytest

from desktop_bridge.audio_devices import AudioDevice, DeviceError
from desktop_bridge.main import main
from desktop_bridge.microphone import (
    CaptureConfig, CaptureError, PhraseSegmenter, capture_microphone,
    choose_input_rate, encode_phrase,
)


MIC = AudioDevice(23, "USB Microphone", 1, 0, 48000, "Windows WASAPI")


def test_input_rate_selection_and_output_only_rejection() -> None:
    class Backend:
        def check_input_settings(self, *, samplerate, **_):
            if samplerate != 44100:
                raise RuntimeError("unsupported")

    assert choose_input_rate(MIC, Backend()) == 44100
    with pytest.raises(DeviceError, match="no input channels"):
        choose_input_rate(AudioDevice(18, "CABLE Input", 0, 2, 48000), Backend())


def test_pcm_wav_is_mono_16bit_16khz_after_resampling() -> None:
    data = np.sin(np.arange(4800) * 2 * np.pi * 440 / 48000).astype(np.float32) * 0.1
    phrase = encode_phrase(data, 48000, 12345)
    with wave.open(BytesIO(phrase.wav_bytes), "rb") as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) == (1, 2, 16000)
        assert reader.getnframes() == 1600
    assert phrase.capture_duration_ms == pytest.approx(100)
    assert phrase.speech_end_at_ms == 12345
    assert phrase.phrase_id
    with pytest.raises(CaptureError, match="empty"):
        encode_phrase(np.array([], dtype=np.float32), 48000, 0)


def test_vad_onset_silence_and_short_noise() -> None:
    vad = PhraseSegmenter(16000)
    quiet = np.zeros(320, dtype=np.float32)
    speech = np.ones(320, dtype=np.float32) * 0.08
    for _ in range(10):
        assert vad.push(quiet) is None
    for _ in range(5):
        assert vad.push(speech) is None
    for _ in range(40):
        assert vad.push(quiet) is None  # short noise is discarded
    for _ in range(36):
        vad.push(speech)
    result = None
    for _ in range(40):
        result = vad.push(quiet, 5000) or result
    assert result is not None
    assert result.capture_duration_ms >= 600
    assert result.speech_end_at_ms == pytest.approx(5000 - 700, abs=100)


def test_vad_maximum_phrase_drops_uninterrupted_audio() -> None:
    vad = PhraseSegmenter(16000, CaptureConfig(max_phrase_seconds=1))
    speech = np.ones(320, dtype=np.float32) * 0.1
    for _ in range(50):
        assert vad.push(speech) is None
    assert vad.dropped_long_phrases == 1
    assert not vad.active
    assert vad.push(np.array([], dtype=np.float32)) is None


class FakeStream:
    def __init__(self, callback, blocksize, *, overflow=False, interrupted=False):
        self.callback = callback
        self.blocksize = blocksize or 960
        self.overflow = overflow
        self.interrupted = interrupted
        self.active = True
        self.closed = False

    def __enter__(self):
        if self.interrupted:
            raise KeyboardInterrupt
        status = type("Status", (), {"input_overflow": self.overflow, "__bool__": lambda obj: self.overflow})()
        self.callback(np.ones((self.blocksize, 1), dtype=np.float32) * 0.08, self.blocksize, None, status)
        return self

    def __exit__(self, *_):
        self.closed = True


class FakeBackend:
    def __init__(self, **flags):
        self.flags = flags
        self.stream = None
        self.opens = 0

    def sleep(self, _milliseconds):
        pass

    def check_input_settings(self, **_):
        pass

    def InputStream(self, **kwargs):
        self.opens += 1
        self.stream = FakeStream(kwargs["callback"], kwargs["blocksize"],
                                 **(self.flags if self.opens > 1 else {}))
        return self.stream


def test_full_queue_counts_dropped_frames_and_closes_stream() -> None:
    class BurstStream(FakeStream):
        def __enter__(self):
            super().__enter__()
            for _ in range(3):
                self.callback(np.zeros((self.blocksize, 1), dtype=np.float32), self.blocksize, None, False)
            return self

    class BurstBackend(FakeBackend):
        def InputStream(self, **kwargs):
            self.opens += 1
            stream_type = BurstStream if self.opens > 1 else FakeStream
            self.stream = stream_type(kwargs["callback"], kwargs["blocksize"])
            return self.stream

    backend = BurstBackend()
    summary = capture_microphone(MIC, lambda _: None, duration=0.03, backend=backend,
                                 config=CaptureConfig(queue_blocks=1), report=lambda _: None)
    assert summary.dropped_frames >= 3 * backend.stream.blocksize
    assert backend.stream.closed


def test_stream_cleanup_and_bounded_capture() -> None:
    backend = FakeBackend()
    summary = capture_microphone(MIC, lambda _: None, duration=0.03, backend=backend, report=lambda _: None)
    assert summary.phrases == 0
    assert backend.stream.closed


def test_overflow_is_counted_and_queue_is_bounded() -> None:
    backend = FakeBackend(overflow=True)
    summary = capture_microphone(MIC, lambda _: None, duration=0.03, backend=backend,
                                 config=CaptureConfig(queue_blocks=1), report=lambda _: None)
    assert summary.dropped_frames >= backend.stream.blocksize
    assert backend.stream.closed


def test_ctrl_c_is_clean_and_never_propagates() -> None:
    backend = FakeBackend(interrupted=True)
    messages = []
    summary = capture_microphone(MIC, lambda _: None, backend=backend, report=messages.append)
    assert summary.phrases == 0
    assert any("Ctrl+C" in message for message in messages)


def test_ctrl_c_inside_active_stream_releases_device() -> None:
    class InterruptingStream(FakeStream):
        @property
        def active(self):
            raise KeyboardInterrupt

        @active.setter
        def active(self, _):
            pass

    class InterruptingBackend(FakeBackend):
        def InputStream(self, **kwargs):
            self.opens += 1
            stream_type = InterruptingStream if self.opens > 1 else FakeStream
            self.stream = stream_type(kwargs["callback"], kwargs["blocksize"])
            return self.stream

    backend = InterruptingBackend()
    summary = capture_microphone(MIC, lambda _: None, backend=backend, report=lambda _: None)
    assert summary.phrases == 0
    assert backend.stream.closed


def test_cli_requires_explicit_valid_input(monkeypatch, capsys) -> None:
    monkeypatch.setattr("desktop_bridge.main.list_devices", lambda: [MIC, AudioDevice(18, "CABLE Input", 0, 2, 48000)])
    assert main(["capture", "--device", "999", "--duration", "1"]) == 1
    assert main(["capture", "--device", "18", "--duration", "1"]) == 1
    assert main(["capture", "--device", "USB", "--duration", "1"]) == 1
    assert "Error:" in capsys.readouterr().err


def test_virtual_input_requires_extra_opt_in(monkeypatch) -> None:
    cable = AudioDevice(22, "CABLE Output", 2, 0, 48000)
    monkeypatch.setattr("desktop_bridge.main.list_devices", lambda: [cable])
    assert main(["capture", "--device", "22", "--duration", "1"]) == 1


def test_stream_failure_is_actionable_and_cleanup_runs() -> None:
    class BrokenBackend(FakeBackend):
        def InputStream(self, **_):
            raise RuntimeError("device unavailable")

    with pytest.raises(CaptureError, match="could not deliver input frames"):
        capture_microphone(MIC, lambda _: None, duration=0.01, backend=BrokenBackend(), report=lambda _: None)
