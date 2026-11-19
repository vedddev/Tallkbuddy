from io import BytesIO
import wave

import numpy as np
import pytest

from desktop_bridge.audio_devices import AudioDevice, DeviceError
from desktop_bridge.mic_diagnostics import format_probe, input_candidates, probe_input_formats
from desktop_bridge.microphone import CaptureError, capture_microphone


MIC = AudioDevice(24, "Realtek Mic WDM-KS", 2, 0, 44100, "Windows WDM-KS")


class Stream:
    def __init__(self, backend, kwargs):
        self.backend = backend
        self.kwargs = kwargs
        self.active = True
        self.closed = False

    def __enter__(self):
        channels = self.kwargs["channels"]
        callback = self.kwargs["callback"]
        if channels == 2:
            if self.backend.opens >= 3:
                callback(np.full((35280, 2), 0.08, dtype=np.float32), 35280, None, False)
                callback(np.zeros((35280, 2), dtype=np.float32), 35280, None, False)
            else:
                callback(np.zeros((4410, 2), dtype=np.float32), 4410, None, False)
        return self

    def __exit__(self, *_):
        self.closed = True


class StereoOnlyBackend:
    def __init__(self):
        self.opens = 0
        self.streams = []

    def check_input_settings(self, **kwargs):
        if kwargs["samplerate"] != 44100:
            raise RuntimeError("Unsupported rate")

    def InputStream(self, **kwargs):
        self.opens += 1
        stream = Stream(self, kwargs)
        self.streams.append(stream)
        return stream

    def sleep(self, _ms):
        pass


def test_native_rate_first_and_output_only_rejected() -> None:
    assert input_candidates(MIC)[:2] == [(44100, 1), (44100, 2)]
    with pytest.raises(DeviceError, match="output-only"):
        input_candidates(AudioDevice(14, "CABLE Input", 0, 2, 48000))


def test_probe_distinguishes_opened_but_no_frames_from_usable_stereo() -> None:
    backend = StereoOnlyBackend()
    probes = probe_input_formats(MIC, backend=backend, stop_at_first_usable=True)
    assert len(probes) == 2
    assert probes[0].opened and not probes[0].usable and probes[0].frames == 0
    assert probes[1].usable and probes[1].sample_rate == 44100 and probes[1].channels == 2
    assert all(stream.closed for stream in backend.streams)


def test_host_api_open_error_is_reported_without_device_fallback() -> None:
    class PortAudioError(Exception):
        pass

    class FailingBackend:
        def check_input_settings(self, **_):
            pass

        def InputStream(self, **_):
            raise PortAudioError("Invalid device", -9996)

    probes = probe_input_formats(MIC, backend=FailingBackend())
    assert all(not probe.usable for probe in probes)
    assert "PortAudio -9996" in format_probe(probes[0])
    assert probes[0].sample_rate == MIC.default_samplerate


def test_capture_uses_native_stereo_then_downmixes_to_16khz_mono_wav() -> None:
    backend = StereoOnlyBackend()
    phrases = []
    summary = capture_microphone(MIC, phrases.append, duration=0.05, backend=backend, report=lambda _: None)
    assert summary.phrases == 1
    assert backend.streams[-1].kwargs["samplerate"] == 44100
    assert backend.streams[-1].kwargs["channels"] == 2
    with wave.open(BytesIO(phrases[0].wav_bytes), "rb") as reader:
        assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (16000, 1, 2)
        assert reader.getnframes() > 10000
    assert all(stream.closed for stream in backend.streams)


def test_callback_malformed_buffer_stops_cleanly() -> None:
    class MalformedStream(Stream):
        def __enter__(self):
            if self.backend.opens < 3:
                return super().__enter__()
            self.kwargs["callback"](np.zeros(10, dtype=np.float32), 10, None, False)
            return self

    class MalformedBackend(StereoOnlyBackend):
        def InputStream(self, **kwargs):
            self.opens += 1
            stream = MalformedStream(self, kwargs)
            self.streams.append(stream)
            return stream

    backend = MalformedBackend()
    with pytest.raises(CaptureError, match="callback failed"):
        capture_microphone(MIC, lambda _: None, duration=0.2, backend=backend, report=lambda _: None)
    assert all(stream.closed for stream in backend.streams)
