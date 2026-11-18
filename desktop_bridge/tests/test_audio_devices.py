import pytest

from desktop_bridge.audio_devices import AudioDevice, DeviceError, format_device, list_devices, select_output_device
from desktop_bridge.config import load_language_registry


class FakeBackend:
    def query_devices(self):
        return [
            {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
            {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
            {"name": "CABLE Output (VB-Audio Virtual Cable)", "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 48000},
        ]


def test_lists_cable_playback_and_recording_sides() -> None:
    devices = list_devices(FakeBackend())
    assert devices[1].cable_input
    assert devices[2].cable_output
    assert "CABLE Input playback" in format_device(devices[1])
    assert "CABLE Output recording" in format_device(devices[2])
    assert select_output_device(devices).index == 1
    assert select_output_device(devices, "1").index == 1
    assert select_output_device(devices, "Speakers").index == 0


def test_never_uses_recording_side_as_output() -> None:
    devices = list_devices(FakeBackend())
    with pytest.raises(DeviceError, match="not an available playback"):
        select_output_device(devices, "2")


def test_missing_or_ambiguous_cable_requires_explicit_selection() -> None:
    speaker = AudioDevice(0, "Speakers", 0, 2, 48000)
    cable_a = AudioDevice(1, "CABLE Input (MME)", 0, 2, 48000)
    cable_b = AudioDevice(2, "CABLE Input (WASAPI)", 0, 2, 48000)
    with pytest.raises(DeviceError, match="not found"):
        select_output_device([speaker])
    with pytest.raises(DeviceError, match="Multiple playback devices"):
        select_output_device([cable_a, cable_b])
    assert select_output_device([cable_a, cable_b], 2) == cable_b


def test_no_playback_device_reports_clear_error() -> None:
    with pytest.raises(DeviceError, match="No Windows playback devices"):
        select_output_device([AudioDevice(0, "Microphone", 1, 0, 48000)])


def test_shared_language_registry_preserves_existing_codes_and_provider_mappings() -> None:
    registry = {language.code: language for language in load_language_registry()}
    assert len(registry) == 10
    assert {code for code, language in registry.items() if language.api_enabled} == {"en", "hi", "mr", "es", "de", "fr", "ja", "ru", "zh-CN", "ko"}
    assert registry["zh-CN"].whisper_code == "zh"
    assert registry["hi"].speech_tag == "hi-IN"
