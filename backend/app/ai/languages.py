"""Canonical language codes and provider hints from the shared registry."""

import json
from pathlib import Path


REGISTRY_PATH = Path(__file__).resolve().parents[3] / "shared" / "languages.json"
_REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
LANGUAGE_NAMES: dict[str, str] = {
    entry["code"]: entry["name"] for entry in _REGISTRY if entry["api_enabled"]
}
WHISPER_LANGUAGE_CODES: dict[str, str] = {
    entry["code"]: entry["whisper_code"] for entry in _REGISTRY if entry["api_enabled"]
}
LANGUAGE_CODES: dict[str, str] = {
    **{code.casefold(): code for code in LANGUAGE_NAMES},
    **{name.casefold(): code for code, name in LANGUAGE_NAMES.items()},
    "zh": "zh-CN",
    "chinese": "zh-CN",
    "mandarin": "zh-CN",
    "mandarin chinese": "zh-CN",
    "chinese mandarin": "zh-CN",
}


def parse_target_language(value: str) -> str:
    """Accept a supported language name or code, returning its canonical code."""

    code = LANGUAGE_CODES.get(value.strip().casefold())
    if code is None:
        raise ValueError("Unsupported target language")
    return code


def whisper_language_code(value: str) -> str:
    """Convert an app language code to the ISO-639-1 Whisper language hint."""

    return WHISPER_LANGUAGE_CODES[parse_target_language(value)]


def normalize_detected_language(value: str | None) -> str | None:
    """Normalize known provider labels; preserve unknown labels for compatibility."""

    if not value or not value.strip():
        return None
    normalized = value.strip().casefold()
    return LANGUAGE_CODES.get(normalized, normalized)
