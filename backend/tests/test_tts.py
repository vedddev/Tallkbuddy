"""Mock Azure Speech; never contact or bill a live provider in automated tests."""

import asyncio
from io import BytesIO
import wave

import httpx
import pytest
from pydantic import SecretStr

from app.ai.tts import TTSError, VOICES, synthesize_wav, validate_speech_wav
from app.core.config import Settings


def pcm_wav(rate: int = 24000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x01\x00" * 1600)
    return buffer.getvalue()


def test_tts_voice_map_covers_shared_languages() -> None:
    from app.ai.languages import LANGUAGE_NAMES
    assert set(VOICES) == set(LANGUAGE_NAMES)


def test_tts_sends_escaped_text_and_returns_valid_pcm_without_logging_key() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode("utf-8")
        seen["format"] = request.headers["X-Microsoft-OutputFormat"]
        assert request.headers["Ocp-Apim-Subscription-Key"] == "private-test-key"
        return httpx.Response(200, content=pcm_wav())

    settings = Settings(_env_file=None, azure_speech_key=SecretStr("private-test-key"), azure_speech_region="eastus")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await synthesize_wav("Bonjour <&>", "fr", settings, client=client)
    assert asyncio.run(run()) == pcm_wav()
    assert seen["url"] == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert "Bonjour &lt;&amp;&gt;" in seen["body"]
    assert seen["format"] == "riff-24khz-16bit-mono-pcm"


def test_tts_rejects_unconfigured_invalid_region_and_bad_audio() -> None:
    with pytest.raises(TTSError, match="not configured"):
        asyncio.run(synthesize_wav("Hello", "en", Settings(
            _env_file=None, azure_speech_key=None, azure_speech_region=None,
        )))
    bad_region = Settings(_env_file=None, azure_speech_key=SecretStr("x"), azure_speech_region="evil.example/path")
    with pytest.raises(TTSError, match="not configured"):
        asyncio.run(synthesize_wav("Hello", "en", bad_region))
    with pytest.raises(TTSError, match="Invalid speech"):
        validate_speech_wav(b"not a wav", 1024)
    with pytest.raises(TTSError, match="Incompatible"):
        validate_speech_wav(pcm_wav(rate=16000), 1024 * 1024)


@pytest.mark.parametrize("status,category", [
    (401, "authentication"), (403, "authentication"), (429, "rate_limit"),
    (400, "invalid_request_or_voice"), (404, "invalid_request_or_voice"),
    (503, "provider_server"),
])
def test_tts_provider_errors_are_categorized_without_secrets(status, category, caplog) -> None:
    secret = "private-test-key"
    settings = Settings(_env_file=None, azure_speech_key=SecretStr(secret), azure_speech_region="eastus")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="provider response with private text")
        )) as client:
            await synthesize_wav("private speech text", "hi", settings, client=client)

    with pytest.raises(TTSError, match="unavailable"):
        asyncio.run(run())
    assert f"category={category}" in caplog.text
    assert secret not in caplog.text
    assert "private speech text" not in caplog.text
    assert "provider response" not in caplog.text


def test_tts_timeout_and_invalid_voice_are_safe(caplog) -> None:
    settings = Settings(_env_file=None, azure_speech_key=SecretStr("test-only"), azure_speech_region="eastus")

    async def run_timeout():
        def timeout(request):
            raise httpx.ReadTimeout("private transport detail", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            await synthesize_wav("Hello", "en", settings, client=client)

    with pytest.raises(TTSError, match="unavailable"):
        asyncio.run(run_timeout())
    assert "ReadTimeout" in caplog.text
    assert "private transport detail" not in caplog.text
    with pytest.raises(TTSError, match="unsupported"):
        asyncio.run(synthesize_wav("Hello", "xx", settings))
