"""Decode PCM WAV and play it into an explicitly selected output device."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import math
import wave

import numpy as np

from desktop_bridge.audio_devices import AudioDevice, sounddevice_backend
from desktop_bridge.config import BridgeConfig


class WavError(ValueError):
    """The file is not a supported, bounded PCM WAV."""


class PlaybackError(RuntimeError):
    """The selected Windows output could not play audio."""


@dataclass(frozen=True)
class PcmAudio:
    samples: np.ndarray  # float32, shape (frames, channels)
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return self.samples.shape[0] / self.sample_rate


def _decode_pcm(raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    if sample_width == 3:
        triplets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = triplets[:, 0] | (triplets[:, 1] << 8) | (triplets[:, 2] << 16)
        signed = np.where(values & 0x800000, values - 0x1000000, values)
        return signed.astype(np.float32) / 8388608
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    raise WavError("Only 8-, 16-, 24-, and 32-bit integer PCM WAV files are supported.")


def load_pcm_wav(path: str | Path, config: BridgeConfig | None = None) -> PcmAudio:
    config = config or BridgeConfig()
    wav_path = Path(path)
    if not wav_path.is_file():
        raise WavError(f"WAV file not found: {wav_path}")
    if wav_path.stat().st_size > config.max_wav_bytes:
        raise WavError("WAV file exceeds the configured size limit.")
    try:
        with wave.open(str(wav_path), "rb") as reader:
            channels = reader.getnchannels()
            rate = reader.getframerate()
            width = reader.getsampwidth()
            frames = reader.getnframes()
            if reader.getcomptype() != "NONE" or channels < 1 or channels > 8:
                raise WavError("WAV must use uncompressed PCM with 1 to 8 channels.")
            if rate < 8000 or rate > 192000 or frames < 1:
                raise WavError("WAV sample rate or frame count is invalid.")
            if frames / rate > config.max_wav_seconds:
                raise WavError("WAV duration exceeds the configured limit.")
            if width not in (1, 2, 3, 4):
                raise WavError("Only 8-, 16-, 24-, and 32-bit integer PCM WAV files are supported.")
            raw = reader.readframes(frames)
            if len(raw) != frames * channels * width:
                raise WavError("WAV audio data is incomplete.")
    except (wave.Error, EOFError) as exc:
        raise WavError("Invalid or unsupported WAV file; use uncompressed integer PCM.") from exc
    return PcmAudio(_decode_pcm(raw, width).reshape(frames, channels), rate)


def resample_audio(samples: np.ndarray, source_rate: int, output_rate: int) -> np.ndarray:
    if source_rate <= 0 or output_rate <= 0:
        raise WavError("Audio sample rates must be positive.")
    if source_rate == output_rate:
        return samples.astype(np.float32, copy=False)
    output_frames = max(1, int(round(samples.shape[0] * output_rate / source_rate)))
    positions = np.minimum(np.arange(output_frames, dtype=np.float64) * source_rate / output_rate, samples.shape[0] - 1)
    input_positions = np.arange(samples.shape[0], dtype=np.float64)
    return np.column_stack([
        np.interp(positions, input_positions, samples[:, channel])
        for channel in range(samples.shape[1])
    ]).astype(np.float32)


def adapt_channels(samples: np.ndarray, output_channels: int) -> np.ndarray:
    if output_channels == 1:
        return samples.mean(axis=1, keepdims=True).astype(np.float32)
    if output_channels == 2:
        if samples.shape[1] == 1:
            return np.repeat(samples, 2, axis=1)
        if samples.shape[1] == 2:
            return samples
        mono = samples.mean(axis=1, keepdims=True)
        return np.repeat(mono, 2, axis=1).astype(np.float32)
    raise PlaybackError("The selected playback device has no supported mono/stereo output.")


def play_wav(path: str | Path, device: AudioDevice, config: BridgeConfig | None = None, backend: Any | None = None) -> PcmAudio:
    config = config or BridgeConfig()
    audio = load_pcm_wav(path, config)
    backend = backend or sounddevice_backend()
    if device.output_channels < 1:
        raise PlaybackError("The selected device is not a playback output. Select CABLE Input, not CABLE Output.")
    channels = min(2, device.output_channels)
    candidates = dict.fromkeys((device.default_samplerate, audio.sample_rate, 48000, 44100))
    output_rate = None
    for rate in candidates:
        if not 8000 <= rate <= 192000:
            continue
        try:
            backend.check_output_settings(device=device.index, samplerate=rate, channels=channels, dtype="float32")
        except Exception:
            continue
        output_rate = rate
        break
    if output_rate is None:
        raise PlaybackError("No compatible sample rate/mono-stereo format is available on this playback device.")
    data = adapt_channels(resample_audio(audio.samples, audio.sample_rate, output_rate), channels)
    try:
        backend.play(data, samplerate=output_rate, device=device.index, blocking=True)
    except KeyboardInterrupt as exc:
        backend.stop()
        raise PlaybackError("Playback interrupted.") from exc
    except Exception as exc:
        raise PlaybackError("Audio playback failed. Check whether the selected device is connected and available.") from exc
    return audio


def write_test_wav(path: str | Path, seconds: float = 2.0, rate: int = 48000) -> None:
    """Write a quiet PCM tone for local routing diagnostics; this is not TTS."""

    if not 0.1 <= seconds <= 10:
        raise ValueError("Test tone length must be between 0.1 and 10 seconds")
    count = int(seconds * rate)
    frames = np.arange(count, dtype=np.float64)
    tone = (np.sin(2 * math.pi * 440 * frames / rate) * 0.12 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(tone.tobytes())
