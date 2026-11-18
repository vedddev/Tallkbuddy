"""Discover and select PortAudio devices without changing Windows defaults."""

from dataclasses import dataclass
from typing import Any


class DeviceError(RuntimeError):
    """A requested audio device cannot be used."""


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    input_channels: int
    output_channels: int
    default_samplerate: int

    @property
    def cable_input(self) -> bool:
        return "cable input" in self.name.casefold() and self.output_channels > 0

    @property
    def cable_output(self) -> bool:
        return "cable output" in self.name.casefold() and self.input_channels > 0


def sounddevice_backend() -> Any:
    try:
        import sounddevice
    except (ImportError, OSError) as exc:
        raise DeviceError("sounddevice is unavailable. Install desktop_bridge/requirements.txt and check PortAudio.") from exc
    return sounddevice


def list_devices(backend: Any | None = None) -> list[AudioDevice]:
    backend = backend or sounddevice_backend()
    try:
        raw_devices = backend.query_devices()
    except Exception as exc:
        raise DeviceError("Windows audio devices could not be queried. Check the audio service and device drivers.") from exc
    return [
        AudioDevice(
            index=index,
            name=str(raw["name"]),
            input_channels=int(raw["max_input_channels"]),
            output_channels=int(raw["max_output_channels"]),
            default_samplerate=int(round(float(raw["default_samplerate"]))),
        )
        for index, raw in enumerate(raw_devices)
    ]


def select_output_device(devices: list[AudioDevice], selector: str | int | None = None) -> AudioDevice:
    outputs = [device for device in devices if device.output_channels > 0]
    if not outputs:
        raise DeviceError("No Windows playback devices are available.")
    if selector is None or str(selector).strip() == "":
        matches = [device for device in outputs if device.cable_input]
        if not matches:
            raise DeviceError("VB-CABLE playback device 'CABLE Input' was not found. Install VB-CABLE or pass --device.")
    elif str(selector).strip().isdigit():
        index = int(str(selector).strip())
        matches = [device for device in outputs if device.index == index]
        if not matches:
            raise DeviceError(f"Device {index} is not an available playback device. Run 'devices' to list outputs.")
    else:
        name = str(selector).strip().casefold()
        matches = [device for device in outputs if name in device.name.casefold()]
        if not matches:
            raise DeviceError(f"No playback device matches '{selector}'. Run 'devices' to list outputs.")
    if len(matches) > 1:
        indices = ", ".join(str(device.index) for device in matches)
        raise DeviceError(f"Multiple playback devices match ({indices}). Choose one with --device INDEX.")
    return matches[0]


def format_device(device: AudioDevice) -> str:
    role = "CABLE Input playback" if device.cable_input else "CABLE Output recording" if device.cable_output else ""
    return (
        f"{device.index:>3}  {device.name}  "
        f"[in={device.input_channels}, out={device.output_channels}, default={device.default_samplerate} Hz]"
        f"{'  <-- ' + role if role else ''}"
    )
