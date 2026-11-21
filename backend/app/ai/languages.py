"""Canonical language codes and provider hints from the shared registry."""

import json
import re
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

# Whisper may return a language name or an ISO code. These additional names
# remain valid source metadata, even though they are not target UI options.
OTHER_PROVIDER_LANGUAGES = {
    "italian": "it", "portuguese": "pt", "arabic": "ar", "bengali": "bn",
    "tamil": "ta", "telugu": "te", "urdu": "ur", "dutch": "nl",
    "turkish": "tr", "polish": "pl", "ukrainian": "uk", "indonesian": "id",
    "vietnamese": "vi", "thai": "th", "swedish": "sv", "punjabi": "pa",
    "gujarati": "gu", "kannada": "kn", "malayalam": "ml",
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
    """Normalize provider metadata; return None for unrecognized labels."""

    if not value or not value.strip():
        return None
    normalized = value.strip().casefold()
    if normalized in LANGUAGE_CODES:
        return LANGUAGE_CODES[normalized]
    if normalized in OTHER_PROVIDER_LANGUAGES:
        return OTHER_PROVIDER_LANGUAGES[normalized]
    if re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", normalized):
        base = normalized.split("-", 1)[0]
        return LANGUAGE_CODES.get(base) or (base if base in OTHER_PROVIDER_LANGUAGES.values() else None)
    return None
