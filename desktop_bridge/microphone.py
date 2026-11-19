"""Explicit local microphone capture, phrase segmentation, and in-memory PCM WAV output."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from io import BytesIO
from queue import Empty, Full, Queue
from threading import Event
from typing import Any, Callable
import time
import uuid
import wave

import numpy as np

from desktop_bridge.audio_devices import AudioDevice, DeviceError, sounddevice_backend
from desktop_bridge.mic_diagnostics import format_probe, probe_input_formats
from desktop_bridge.wav_player import resample_audio


class CaptureError(RuntimeError):
    """A microphone stream failed or supplied unusable audio."""


@dataclass(frozen=True)
class CaptureConfig:
    silence_seconds: float = 0.7
    min_speech_seconds: float = 0.6
    max_phrase_seconds: float = 12.0
    onset_seconds: float = 0.12
    preroll_seconds: float = 0.25
    trailing_seconds: float = 0.15
    queue_blocks: int = 64
    output_rate: int = 16000

    def validate(self) -> None:
        if not 0.2 <= self.silence_seconds <= 3:
            raise ValueError("Silence duration must be between 0.2 and 3 seconds.")
        if not 0.1 <= self.min_speech_seconds < self.max_phrase_seconds <= 30:
            raise ValueError("Phrase duration must have 0.1 <= minimum < maximum <= 30 seconds.")
        if self.onset_seconds <= 0 or self.preroll_seconds < self.onset_seconds:
            raise ValueError("Pre-speech padding must be at least as long as speech onset.")
        if self.queue_blocks < 1 or self.output_rate != 16000:
            raise ValueError("Capture queue must be bounded and output rate must be 16000 Hz.")


@dataclass(frozen=True)
class CapturedPhrase:
    phrase_id: str
    wav_bytes: bytes
    capture_duration_ms: float
    speech_end_at_ms: float  # local monotonic clock, meaningful only in this process
    emitted_at_ms: float


def encode_phrase(samples: np.ndarray, source_rate: int, speech_end_at_ms: float,
                  output_rate: int = 16000) -> CapturedPhrase:
    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    if mono.size == 0 or source_rate < 8000:
        raise CaptureError("Cannot encode an empty or invalid phrase.")
    converted = resample_audio(mono.reshape(-1, 1), source_rate, output_rate)[:, 0]
    pcm = (np.clip(converted, -1, 1) * 32767).astype("<i2")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(output_rate)
        writer.writeframes(pcm.tobytes())
    return CapturedPhrase(str(uuid.uuid4()), buffer.getvalue(), mono.size / source_rate * 1000,
                          speech_end_at_ms, time.perf_counter() * 1000)


class PhraseSegmenter:
    """Adaptive RMS voice gate with onset, pre-roll, and silence-based completion."""

    def __init__(self, sample_rate: int, config: CaptureConfig | None = None) -> None:
        self.rate = sample_rate
        self.config = config or CaptureConfig()
        self.config.validate()
        self.noise_floor = 0.002
        self.level = 0.0
        self.dropped_long_phrases = 0
        self.reset()

    def reset(self) -> None:
        self.preroll: deque[np.ndarray] = deque()
        self.preroll_samples = 0
        self.segment: list[np.ndarray] = []
        self.segment_samples = 0
        self.voiced_samples = 0
        self.candidate_samples = 0
        self.trailing_samples = 0
        self.active = False

    def push(self, block: np.ndarray, now_ms: float | None = None) -> CapturedPhrase | None:
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return None
        if not np.all(np.isfinite(data)):
            self.reset()
            return None
        self.level = float(np.sqrt(np.mean(np.square(data.astype(np.float64)))))
        voiced = self.level >= max(0.012, self.noise_floor * 2.8)
        if not voiced:
            self.noise_floor = min(0.02, self.noise_floor * 0.995 + self.level * 0.005)
        if not self.active:
            self.preroll.append(data.copy())
            self.preroll_samples += data.size
            while self.preroll_samples > self.rate * self.config.preroll_seconds and len(self.preroll) > 1:
                self.preroll_samples -= len(self.preroll.popleft())
            self.candidate_samples = self.candidate_samples + data.size if voiced else 0
            if self.candidate_samples < self.rate * self.config.onset_seconds:
                return None
            self.active = True
            self.segment = list(self.preroll)
            self.segment_samples = self.preroll_samples
            self.voiced_samples = self.candidate_samples
            self.preroll.clear()
            self.preroll_samples = 0
            return None
        self.segment.append(data.copy())
        self.segment_samples += data.size
        if voiced:
            self.voiced_samples += data.size
            self.trailing_samples = 0
        else:
            self.trailing_samples += data.size
        if self.trailing_samples >= self.rate * self.config.silence_seconds:
            return self._finish(now_ms)
        if self.segment_samples >= self.rate * self.config.max_phrase_seconds:
            if self.trailing_samples >= self.rate * 0.18:
                return self._finish(now_ms)
            self.dropped_long_phrases += 1
            self.reset()
        return None

    def _finish(self, now_ms: float | None) -> CapturedPhrase | None:
        if self.voiced_samples < self.rate * self.config.min_speech_seconds:
            self.reset()
            return None
        speech_end = (now_ms if now_ms is not None else time.perf_counter() * 1000) - self.trailing_samples / self.rate * 1000
        keep = self.segment_samples - self.trailing_samples + min(self.trailing_samples, int(self.rate * self.config.trailing_seconds))
        samples = np.concatenate(self.segment)[:keep]
        self.reset()
        return encode_phrase(samples, self.rate, speech_end, self.config.output_rate)


@dataclass(frozen=True)
class CaptureSummary:
    phrases: int
    dropped_frames: int
    dropped_long_phrases: int
    elapsed_seconds: float


def choose_input_rate(device: AudioDevice, backend: Any) -> int:
    """Legacy settings preflight; capture uses real-stream probes before choosing a format."""
    if device.input_channels < 1:
        raise DeviceError("Selected device has no input channels. Choose a microphone from 'devices'.")
    for rate in dict.fromkeys((device.default_samplerate, 48000, 44100, 16000)):
        if not 8000 <= rate <= 192000:
            continue
        try:
            backend.check_input_settings(device=device.index, samplerate=rate, channels=1, dtype="float32")
            return rate
        except Exception:
            continue
    raise CaptureError("Selected microphone has no compatible mono float32 input rate. Check its driver and privacy settings.")


def capture_microphone(device: AudioDevice, on_phrase: Callable[[CapturedPhrase], None],
                       *, duration: float | None = None, diagnostics: bool = False,
                       config: CaptureConfig | None = None, backend: Any | None = None,
                       report: Callable[[str], None] = print,
                       stop_event: Event | None = None, pause_event: Event | None = None) -> CaptureSummary:
    """Capture only after an explicit caller action; never persist or transmit WAV bytes."""
    config = config or CaptureConfig()
    config.validate()
    if duration is not None and not 0 < duration <= 3600:
        raise ValueError("Capture duration must be greater than 0 and at most 3600 seconds.")
    backend = backend or sounddevice_backend()
    report(f"Probing selected input {device.index}: {device.name} [{device.host_api}].")
    try:
        probes = probe_input_formats(device, backend=backend, stop_at_first_usable=True)
    except KeyboardInterrupt:
        report("Capture stopped by Ctrl+C.")
        return CaptureSummary(0, 0, 0, 0)
    usable = next((probe for probe in probes if probe.usable), None)
    if usable is None:
        details = "; ".join(format_probe(probe) for probe in probes)
        raise CaptureError(
            "Selected microphone could not deliver input frames. " + details +
            ". Re-list indices, check Windows microphone privacy and exclusive-mode use, "
            "or explicitly select another host-API entry for the same microphone."
        )
    rate, channels = usable.sample_rate, usable.channels
    blocks: Queue[tuple[np.ndarray, float]] = Queue(maxsize=config.queue_blocks)
    dropped_frames = 0
    stream_error: str | None = None

    def callback(indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        nonlocal dropped_frames, stream_error
        if status:
            if getattr(status, "input_overflow", False):
                dropped_frames += frames
            else:
                stream_error = "Microphone stream reported an error. Check the selected device."
        if pause_event is not None and pause_event.is_set():
            return
        try:
            incoming = np.asarray(indata, dtype=np.float32)
            if incoming.ndim != 2 or incoming.shape != (frames, channels):
                raise ValueError("Malformed microphone callback buffer")
            blocks.put_nowait((incoming.copy(), time.perf_counter() * 1000))
        except Full:
            dropped_frames += frames
        except Exception:
            stream_error = "Microphone callback failed while copying input frames. Stop capture and check the selected device."

    segmenter = PhraseSegmenter(rate, config)
    phrase_count = 0
    start = time.perf_counter()
    last_report = start
    previous_drops = 0
    report(f"Capturing device {device.index}: {device.name} [{device.host_api}, {rate} Hz, {channels} input channel(s); 16 kHz mono WAV output]. Press Ctrl+C to stop.")
    try:
        with backend.InputStream(device=device.index, samplerate=rate, channels=channels, dtype="float32",
                                 blocksize=0, callback=callback) as stream:
            while (duration is None or time.perf_counter() - start < duration) and (stop_event is None or not stop_event.is_set()):
                if stream_error:
                    raise CaptureError(stream_error)
                if hasattr(stream, "active") and not stream.active:
                    raise CaptureError("Microphone disconnected or input stream stopped. Recheck the device index.")
                try:
                    block, captured_at_ms = blocks.get(timeout=0.1)
                except Empty:
                    continue
                if pause_event is not None and pause_event.is_set():
                    segmenter.reset()
                    continue
                if dropped_frames != previous_drops:
                    segmenter.reset()  # never emit an incomplete phrase after lost samples
                    previous_drops = dropped_frames
                mono = block.mean(axis=1) if block.shape[1] > 1 else block[:, 0]
                phrase = segmenter.push(mono, captured_at_ms)
                if phrase is not None:
                    on_phrase(phrase)
                    phrase_count += 1
                    report(f"Phrase {phrase_count}: id={phrase.phrase_id}, duration={phrase.capture_duration_ms / 1000:.2f}s, WAV={len(phrase.wav_bytes)} bytes")
                now = time.perf_counter()
                if diagnostics and now - last_report >= 1:
                    report(f"Audio level={segmenter.level:.3f}; {'speech' if segmenter.active else 'silence'}; phrases={phrase_count}; dropped frames={dropped_frames}")
                    last_report = now
    except KeyboardInterrupt:
        report("Capture stopped by Ctrl+C.")
    except CaptureError:
        raise
    except Exception as exc:
        code = next((part for part in getattr(exc, "args", ()) if isinstance(part, int)), None)
        if code == -9996:
            raise CaptureError(
                "Microphone could not open (PortAudio -9996: invalid device). Re-list indices, "
                "check Windows microphone privacy, and try another host API for this microphone."
            ) from exc
        raise CaptureError(
            f"Microphone capture failed{' (PortAudio ' + str(code) + ')' if code is not None else ''}. "
            "Check device availability and Windows microphone permission."
        ) from exc
    finally:
        segmenter.reset()
        while not blocks.empty():
            try:
                blocks.get_nowait()
            except Empty:
                break
    return CaptureSummary(phrase_count, dropped_frames, segmenter.dropped_long_phrases,
                          time.perf_counter() - start)
