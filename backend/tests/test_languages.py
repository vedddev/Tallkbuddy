"""Shared registry, validation, and provider-specific language hints."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.languages import LANGUAGE_NAMES, normalize_detected_language, parse_target_language, whisper_language_code
from app.ai.schemas import TranslationRequest
from app.ai.service import AIService
from app.core.config import Settings
from app.ws.protocol import StartMessage


ALL_CODES = ("en", "hi", "mr", "es", "de", "fr", "ja", "ru", "zh-CN", "ko")


@pytest.mark.parametrize("code", ALL_CODES)
def test_all_ten_codes_validate_for_rest_and_websocket(code: str) -> None:
    assert code in LANGUAGE_NAMES
    assert parse_target_language(code) == code
    assert TranslationRequest(text="Hello", target_language=code).target_language == code
    start = StartMessage(type="start", target_language=code, source_language=code, audio_format="wav")
    assert start.target_language == code
    assert start.source_language == code


def test_mandarin_aliases_and_whisper_hint() -> None:
    assert parse_target_language("zh-cn") == "zh-CN"
    assert parse_target_language("Chinese (Mandarin)") == "zh-CN"
    assert parse_target_language("zh") == "zh-CN"
    assert whisper_language_code("zh-CN") == "zh"
    assert normalize_detected_language("Chinese") == "zh-CN"


@pytest.mark.parametrize("code", ALL_CODES)
def test_whisper_hints_are_iso_639_1_codes(code: str) -> None:
    hint = whisper_language_code(code)
    assert len(hint) == 2 and hint.isascii() and hint.islower()


def test_transcription_sends_mandarin_hint_and_normalizes_detection() -> None:
    create = AsyncMock(return_value=SimpleNamespace(text="你好", language="Chinese"))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    service = AIService(client, Settings(_env_file=None))
    result = asyncio.run(service.transcribe(b"RIFFdata", "sample.wav", "zh-CN"))
    assert create.await_args.kwargs["language"] == "zh"
    assert result.detected_language == "zh-CN"


@pytest.mark.parametrize("provider_label,expected", [
    ("English", "en"), ("Hindi", "hi"), ("Marathi", "mr"),
    ("hi-IN", "hi"), ("Italian", "it"), ("it", "it"),
    ("Unrecognized Provider Label", None), (None, None),
])
def test_auto_detection_uses_provider_metadata_without_language_hint(provider_label, expected) -> None:
    create = AsyncMock(return_value=SimpleNamespace(text="spoken words", language=provider_label))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    result = asyncio.run(AIService(client, Settings(_env_file=None)).transcribe(b"RIFFdata", "sample.wav"))
    assert "language" not in create.await_args.kwargs
    assert create.await_args.kwargs["response_format"] == "verbose_json"
    assert result.detected_language == expected


def test_manual_source_hint_is_preserved_when_provider_reports_another_language() -> None:
    create = AsyncMock(return_value=SimpleNamespace(text="नमस्कार", language="Hindi"))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    result = asyncio.run(AIService(client, Settings(_env_file=None)).transcribe(b"RIFFdata", "sample.wav", "mr"))
    assert create.await_args.kwargs["language"] == "mr"
    assert result.detected_language == "hi"
