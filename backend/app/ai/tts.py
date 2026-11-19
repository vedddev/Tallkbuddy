"""Opt-in Azure Speech WAV synthesis; no text, keys, or provider bodies in logs."""

from __future__ import annotations

from io import BytesIO
import logging
import re
import wave
from xml.sax.saxutils import escape

import httpx

from app.core.config import Settings


logger = logging.getLogger(__name__)
REGION_RE = re.compile(r"[a-z0-9-]{2,40}\Z")
VOICES = {
    "en": ("en-US", "en-US-JennyNeural"),
    "hi": ("hi-IN", "hi-IN-SwaraNeural"),
    "mr": ("mr-IN", "mr-IN-AarohiNeural"),
    "es": ("es-ES", "es-ES-ElviraNeural"),
    "de": ("de-DE", "de-DE-KatjaNeural"),
    "fr": ("fr-FR", "fr-FR-DeniseNeural"),
    "ja": ("ja-JP", "ja-JP-NanamiNeural"),
    "ru": ("ru-RU", "ru-RU-SvetlanaNeural"),
    "zh-CN": ("zh-CN", "zh-CN-XiaoxiaoNeural"),
    "ko": ("ko-KR", "ko-KR-SunHiNeural"),
}


class TTSError(RuntimeError):
    pass


def tts_configured(settings: Settings) -> bool:
    return bool(settings.azure_speech_key and settings.azure_speech_key.get_secret_value() and
                not settings.azure_speech_key.get_secret_value().startswith("replace-with-") and
                settings.azure_speech_region and REGION_RE.fullmatch(settings.azure_speech_region))


def validate_speech_wav(audio: bytes, max_bytes: int) -> None:
    if not 44 <= len(audio) <= max_bytes or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise TTSError("Invalid speech audio")
    if int.from_bytes(audio[4:8], "little") != len(audio) - 8:
        raise TTSError("Incomplete speech audio")
    try:
        with wave.open(BytesIO(audio), "rb") as reader:
            if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype()) != (1, 2, 24000, "NONE"):
                raise TTSError("Incompatible speech audio")
            if not 0 < reader.getnframes() <= 24000 * 30:
                raise TTSError("Speech audio exceeds duration limit")
            if len(reader.readframes(reader.getnframes())) != reader.getnframes() * 2:
                raise TTSError("Incomplete speech samples")
    except (EOFError, wave.Error) as exc:
        raise TTSError("Invalid speech WAV") from exc


async def synthesize_wav(text: str, language: str, settings: Settings, *, client: httpx.AsyncClient | None = None) -> bytes:
    key = settings.azure_speech_key.get_secret_value() if settings.azure_speech_key else ""
    region = settings.azure_speech_region or ""
    if not tts_configured(settings):
        raise TTSError("Speech service is not configured")
    if language not in VOICES or not text.strip() or len(text) > 500:
        raise TTSError("Speech language or length is unsupported")
    locale, voice = VOICES[language]
    ssml = (f'<speak version="1.0" xml:lang="{locale}" '
            f'xmlns="http://www.w3.org/2001/10/synthesis"><voice name="{voice}">'
            f'{escape(text)}</voice></speak>')
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
        "User-Agent": "TalkBuddy",
    }
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=settings.tts_timeout_seconds)
    try:
        async with client.stream(
            "POST", f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            content=ssml.encode("utf-8"), headers=headers,
        ) as response:
            if response.status_code != 200:
                status = response.status_code
                category = (
                    "authentication" if status in (401, 403) else
                    "rate_limit" if status == 429 else
                    "invalid_request_or_voice" if status in (400, 404, 422) else
                    "provider_server" if status >= 500 else "provider_other"
                )
                logger.warning("Speech synthesis failed category=%s status=%s", category, status)
                raise TTSError("Speech provider unavailable")
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > settings.tts_max_audio_bytes:
                    raise TTSError("Speech audio exceeds size limit")
        audio = bytes(chunks)
        validate_speech_wav(audio, settings.tts_max_audio_bytes)
        return audio
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning("Speech synthesis transport failure category=%s", type(exc).__name__)
        raise TTSError("Speech provider unavailable") from exc
    finally:
        if owns_client:
            await client.aclose()
