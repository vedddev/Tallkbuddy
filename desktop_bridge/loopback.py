"""Explicit, bounded local VB-CABLE receive check; recordings remain in memory."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np

from desktop_bridge.audio_devices import AudioDevice, DeviceError, sounddevice_backend
from desktop_bridge.config import BridgeConfig
from desktop_bridge.wav_player import PlaybackError, WavError, load_pcm_wav, play_wav


class LoopbackError(RuntimeError):
    """CABLE Output could not be recorded for the local check."""


@dataclass(frozen=True)
class LoopbackResult:
    detected: bool
    baseline_rms: float
    received_rms: float
    received_peak: float
    recorded_seconds: float


def verify_loopback(
    path: str | Path,
    output: AudioDevice,
    recording: AudioDevice,
    config: BridgeConfig | None = None,
    backend: Any | None = None,
) -> LoopbackResult:
    """Play a short WAV into CABLE Input while monitoring CABLE Output locally."""

    if not output.cable_input:
        raise DeviceError("Loopback output must be CABLE Input, the playback side of VB-CABLE.")
    if not recording.cable_output:
        raise DeviceError("Loopback input must be CABLE Output, the recording side of VB-CABLE.")
    config = config or BridgeConfig()
    audio = load_pcm_wav(path, config)
    if audio.duration_seconds > 5:
        raise WavError("Loopback verification requires a WAV of 5 seconds or less.")
    rate = recording.default_samplerate
    if not 8000 <= rate <= 192000:
        raise LoopbackError("CABLE Output has no usable default recording sample rate.")
    channels = min(2, recording.input_channels)
    backend = backend or sounddevice_backend()
    try:
        backend.check_input_settings(
            device=recording.index, samplerate=rate, channels=channels, dtype="float32"
        )
    except Exception as exc:
        raise LoopbackError("CABLE Output cannot record at its default sample rate.") from exc

    baseline: list[np.ndarray] = []
    received: list[np.ndarray] = []
    max_frames = math.ceil((audio.duration_seconds + 1) * rate)
    stored_frames = 0
    phase = "baseline"
    input_error = False

    def capture(indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        nonlocal stored_frames, input_error
        if status:
            input_error = True
        take = min(frames, max_frames - stored_frames)
        if take <= 0:
            return
        mono = np.asarray(indata[:take]).mean(axis=1).astype(np.float32, copy=True)
        (baseline if phase == "baseline" else received).append(mono)
        stored_frames += take

    try:
        with backend.InputStream(
            device=recording.index, samplerate=rate, channels=channels,
            dtype="float32", callback=capture,
        ):
            backend.sleep(250)
            phase = "playback"
            play_wav(path, output, config, backend)
            backend.sleep(250)
    except (PlaybackError, WavError):
        raise
    except Exception as exc:
        raise LoopbackError("CABLE Output recording failed. Check both cable devices and Windows audio permissions.") from exc
    if input_error:
        raise LoopbackError("CABLE Output reported an input stream error during recording.")
    if not received:
        raise LoopbackError("CABLE Output returned no samples during playback.")

    def rms(chunks: list[np.ndarray]) -> float:
        if not chunks:
            return 0.0
        samples = np.concatenate(chunks)
        return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))

    baseline_rms = rms(baseline)
    received_rms = rms(received)
    received_peak = max(float(np.max(np.abs(chunk))) for chunk in received)
    return LoopbackResult(
        detected=received_peak >= 0.02 and received_rms >= max(0.003, baseline_rms * 3),
        baseline_rms=baseline_rms,
        received_rms=received_rms,
        received_peak=received_peak,
        recorded_seconds=sum(len(chunk) for chunk in received) / rate,
    )
