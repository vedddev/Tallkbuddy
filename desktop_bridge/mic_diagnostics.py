"""Bounded, input-only PortAudio probes for an explicitly selected device."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desktop_bridge.audio_devices import AudioDevice, DeviceError, sounddevice_backend


@dataclass(frozen=True)
class InputProbe:
    sample_rate: int
    channels: int
    settings_ok: bool
    opened: bool
    frames: int
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.settings_ok and self.opened and self.frames > 0 and self.error is None


def _error_label(error: Exception) -> str:
    """Return stable driver facts, not arbitrary exception text or audio content."""
    args = getattr(error, "args", ())
    code = next((item for item in args if isinstance(item, int)), None)
    host = next((item for item in args if isinstance(item, tuple) and len(item) >= 2), None)
    label = type(error).__name__
    if code is not None:
        label += f" (PortAudio {code})"
    if host is not None and isinstance(host[1], int):
        label += f" (host code {host[1]})"
    return label


def input_candidates(device: AudioDevice) -> list[tuple[int, int]]:
    if device.input_channels < 1:
        raise DeviceError("Selected device is output-only. Choose a microphone input index from 'devices'.")
    rates = dict.fromkeys((device.default_samplerate, 48000, 44100, 16000))
    channels = (1, 2) if device.input_channels >= 2 else (1,)
    return [(rate, count) for rate in rates if 8000 <= rate <= 192000 for count in channels]


def probe_input_formats(device: AudioDevice, *, backend: Any | None = None,
                        stop_at_first_usable: bool = False) -> list[InputProbe]:
    """Open each candidate briefly and count callback frames; never retain samples."""
    backend = backend or sounddevice_backend()
    results: list[InputProbe] = []
    for rate, channels in input_candidates(device):
        try:
            backend.check_input_settings(device=device.index, samplerate=rate, channels=channels, dtype="float32")
        except Exception as exc:
            results.append(InputProbe(rate, channels, False, False, 0, _error_label(exc)))
            continue

        frames_received = 0
        status_error = False

        def callback(_data: Any, frames: int, _time: Any, status: Any) -> None:
            nonlocal frames_received, status_error
            frames_received += frames
            if status:
                status_error = True

        try:
            with backend.InputStream(
                device=device.index, samplerate=rate, channels=channels,
                dtype="float32", blocksize=0, callback=callback,
            ):
                if hasattr(backend, "sleep"):
                    backend.sleep(300)
                else:
                    import time
                    time.sleep(0.3)
            error = "Input stream reported a status error" if status_error else None
            if frames_received == 0:
                error = "No audio frames arrived"
            result = InputProbe(rate, channels, True, True, frames_received, error)
        except Exception as exc:
            result = InputProbe(rate, channels, True, False, frames_received, _error_label(exc))
        results.append(result)
        if stop_at_first_usable and result.usable:
            break
    return results


def format_probe(probe: InputProbe) -> str:
    check = "ok" if probe.settings_ok else "rejected"
    opened = "ok" if probe.opened else "failed"
    return (f"{probe.sample_rate} Hz, {probe.channels} ch: settings={check}, "
            f"open={opened}, frames={probe.frames}"
            f"{', ' + probe.error if probe.error else ''}")
