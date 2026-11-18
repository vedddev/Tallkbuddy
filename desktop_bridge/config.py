"""Local bridge settings; no Windows audio defaults are changed."""

from dataclasses import dataclass
import json
import os
from pathlib import Path


LANGUAGE_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "shared" / "languages.json"


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    name: str
    native: str
    whisper_code: str
    speech_tag: str
    api_enabled: bool


def load_language_registry() -> tuple[LanguageSpec, ...]:
    """Shared metadata for a later multilingual pipeline; no provider calls here."""

    entries = json.loads(LANGUAGE_REGISTRY_PATH.read_text(encoding="utf-8"))
    languages = tuple(LanguageSpec(**entry) for entry in entries)
    if len({language.code for language in languages}) != len(languages):
        raise ValueError("Language registry contains duplicate codes")
    return languages


@dataclass(frozen=True)
class BridgeConfig:
    preferred_device: str | None = None
    max_wav_bytes: int = 20 * 1024 * 1024
    max_wav_seconds: float = 120.0

    @classmethod
    def from_environment(cls) -> "BridgeConfig":
        device = os.getenv("TALKBUDDY_BRIDGE_DEVICE") or None
        try:
            max_bytes = int(os.getenv("TALKBUDDY_MAX_WAV_BYTES", str(20 * 1024 * 1024)))
            max_seconds = float(os.getenv("TALKBUDDY_MAX_WAV_SECONDS", "120"))
        except ValueError as exc:
            raise ValueError("Bridge size and duration limits must be numbers") from exc
        if not 1024 <= max_bytes <= 200 * 1024 * 1024:
            raise ValueError("TALKBUDDY_MAX_WAV_BYTES must be between 1 KiB and 200 MiB")
        if not 0.1 <= max_seconds <= 600:
            raise ValueError("TALKBUDDY_MAX_WAV_SECONDS must be between 0.1 and 600")
        return cls(device, max_bytes, max_seconds)
