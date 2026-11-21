"""Authenticated, sequential WebSocket translation protocol tests."""

import asyncio
import base64
import io
import logging
import threading
import wave
from time import perf_counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.ai.languages import LANGUAGE_NAMES
from app.ai.schemas import TranscriptionResponse, TranslationResponse
from app.ai.service import AINoSpeechError, AIProviderFailure, AIProviderTimeout, AIProviderUnavailable
from app.db.models import UserSession
from app.ws.protocol import InterimAudioMessage, ReadyMessage, ResultMessage
from app.ws.audio import InvalidAudioChunk, validate_interim_wav
from app.ws.translate import _cancel_interim, _send
from tests.test_auth import AuthHarness, auth_harness  # noqa: F401 - isolated DB fixture


ORIGIN = {"origin": "http://testserver"}
START = {"type": "start", "target_language": "fr", "audio_format": "wav"}


def test_cancel_interim_preserves_parent_cancellation() -> None:
    async def exercise() -> None:
        entered_cleanup = asyncio.Event()

        async def child() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                entered_cleanup.set()
                await asyncio.Event().wait()

        child_task = asyncio.create_task(child(), name="test-interim-child")
        await asyncio.sleep(0)
        parent = asyncio.create_task(_cancel_interim(child_task), name="test-websocket-parent")
        await entered_cleanup.wait()
        parent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await parent

    asyncio.run(exercise())


def wav_chunk() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\x01\x00" * 1600)
    return buffer.getvalue()


def interim_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\x01\x00" * 16000)
    return buffer.getvalue()


def test_interim_metadata_and_wav_validation() -> None:
    from pydantic import ValidationError

    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    assert InterimAudioMessage.model_validate({
        "type": "interim_audio", "phrase_id": phrase_id, "revision": 1, "audio_format": "wav",
    }).revision == 1
    with pytest.raises(ValidationError):
        InterimAudioMessage.model_validate({
            "type": "interim_audio", "phrase_id": phrase_id, "revision": 0, "audio_format": "wav",
        })
    validate_interim_wav(interim_wav(), 256_000)
    with pytest.raises(InvalidAudioChunk):
        validate_interim_wav(wav_chunk(), 256_000)


def test_interim_disabled_by_default_never_calls_provider(ws_harness: AuthHarness) -> None:
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        assert socket.receive_json()["interim_captions"] is False
        socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": 1, "audio_format": "wav"})
        assert socket.receive_json()["code"] == "interim_unavailable"
        socket.send_bytes(interim_wav())
        socket.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000
    ws_harness.ws_service.transcribe.assert_not_awaited()


@pytest.mark.parametrize("detected", ["en", "hi", "mr"])
def test_interim_caption_is_provisional_and_final_pipeline_unchanged(ws_harness: AuthHarness, detected: str) -> None:
    ws_harness.client.app.state.settings.ws_interim_enabled = True
    ws_harness.ws_service.transcribe.return_value = TranscriptionResponse(text="Hello", detected_language=detected)
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        assert socket.receive_json()["interim_captions"] is True
        socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": 1, "audio_format": "wav"})
        socket.send_bytes(interim_wav())
        interim = socket.receive_json()
        assert interim == {"type": "interim_caption", "phrase_id": phrase_id, "revision": 1,
                           "text": "Hello", "is_final": False, "detected_language": detected}
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
        socket.send_json({"type": "stop"})
    assert ws_harness.ws_service.transcribe.await_count == 2
    assert ws_harness.ws_service.transcribe.await_args_list[0].args == (interim_wav(), "interim.wav")
    ws_harness.ws_service.translate.assert_awaited_once()


def test_interim_rate_and_request_limits(ws_harness: AuthHarness) -> None:
    settings = ws_harness.client.app.state.settings
    settings.ws_interim_enabled = True
    settings.ws_interim_min_interval_seconds = 10
    settings.ws_interim_max_requests = 1
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        socket.receive_json()
        for revision in (1, 2):
            socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": revision, "audio_format": "wav"})
            socket.send_bytes(interim_wav())
            response = socket.receive_json()
            assert response["type"] == ("interim_caption" if revision == 1 else "interim_error")
            if revision == 2:
                assert response["code"] == "interim_limit"
        socket.send_json({"type": "stop"})
    assert ws_harness.ws_service.transcribe.await_count == 1


def test_interim_interval_limit_does_not_block_final_audio(ws_harness: AuthHarness) -> None:
    settings = ws_harness.client.app.state.settings
    settings.ws_interim_enabled = True
    settings.ws_interim_min_interval_seconds = 10
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        socket.receive_json()
        for revision in (1, 2):
            socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": revision, "audio_format": "wav"})
            socket.send_bytes(interim_wav())
            response = socket.receive_json()
            assert response["type"] == ("interim_caption" if revision == 1 else "interim_error")
            if revision == 2:
                assert response["code"] == "interim_rate_limit"
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
        socket.send_json({"type": "stop"})
    assert ws_harness.ws_service.transcribe.await_count == 2


def test_interim_provider_timeout_is_safe_and_final_can_continue(ws_harness: AuthHarness) -> None:
    settings = ws_harness.client.app.state.settings
    settings.ws_interim_enabled = True
    settings.ws_interim_timeout_seconds = 1
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    async def slow_then_normal(*args):
        if args[1] == "interim.wav":
            await asyncio.sleep(2)
        return TranscriptionResponse(text="Hello", detected_language="en")
    ws_harness.ws_service.transcribe.side_effect = slow_then_normal
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        socket.receive_json()
        socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": 1, "audio_format": "wav"})
        socket.send_bytes(interim_wav())
        response = socket.receive_json()
        assert response["type"] == "interim_error"
        assert response["code"] == "provider_timeout"
        assert "internal" not in response["message"]
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
        socket.send_json({"type": "stop"})


def test_stop_cancels_interim_provider_call(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.ws_interim_enabled = True
    started = threading.Event()
    cancelled = threading.Event()
    async def slow_transcription(*_args):
        started.set()
        try:
            await asyncio.sleep(20)
        except asyncio.CancelledError:
            cancelled.set()
            raise
    ws_harness.ws_service.transcribe.side_effect = slow_transcription
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        socket.receive_json()
        socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": 1, "audio_format": "wav"})
        socket.send_bytes(interim_wav())
        assert started.wait(2)
        socket.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert cancelled.wait(2)


def test_interim_provider_rate_limit_does_not_translate_preview(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.ws_interim_enabled = True
    ws_harness.ws_service.transcribe.side_effect = AIProviderUnavailable("private provider details")
    phrase_id = "f2d7e257-4174-4512-beb4-9fcc7df57e64"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "interim_captions": True})
        socket.receive_json()
        socket.send_json({"type": "interim_audio", "phrase_id": phrase_id, "revision": 1, "audio_format": "wav"})
        socket.send_bytes(interim_wav())
        response = socket.receive_json()
        assert response["type"] == "interim_error"
        assert response["code"] == "provider_unavailable"
        assert "private" not in response["message"]
        socket.send_json({"type": "stop"})
    ws_harness.ws_service.translate.assert_not_awaited()


def test_optional_timing_metadata_is_numeric_and_contains_no_diagnostics_secrets() -> None:
    websocket = SimpleNamespace(send_json=AsyncMock())
    message = ResultMessage(
        chunk_id=1, original="Hello", translated="Bonjour", detected_language="en",
        target_language="fr", processing_time_ms=820, transcription_time_ms=500,
        translation_time_ms=270,
    )
    assert asyncio.run(_send(websocket, message)) is True
    payload = websocket.send_json.await_args.args[0]
    assert payload["transcription_time_ms"] == 500
    assert payload["translation_time_ms"] == 270
    assert set(payload) == {
        "type", "chunk_id", "original", "translated", "detected_language",
        "target_language", "processing_time_ms", "transcription_time_ms", "translation_time_ms",
    }
    websocket.send_json.reset_mock()
    retry = message.model_copy(update={"transcription_time_ms": None, "translation_time_ms": None})
    assert asyncio.run(_send(websocket, retry)) is True
    retry_payload = websocket.send_json.await_args.args[0]
    assert "transcription_time_ms" not in retry_payload
    assert "translation_time_ms" not in retry_payload


@pytest.mark.parametrize("interim_state", [None, False, True])
def test_ready_serialization_preserves_legacy_null_and_explicit_interim_state(interim_state: bool | None) -> None:
    websocket = SimpleNamespace(send_json=AsyncMock())
    message = ReadyMessage(target_language="fr", source_language=None, interim_captions=interim_state)
    assert asyncio.run(_send(websocket, message)) is True
    payload = websocket.send_json.await_args.args[0]
    assert payload["source_language"] is None
    assert payload["target_language"] == "fr"
    assert payload["audio_format"] == "wav"
    if interim_state is None:
        assert "interim_captions" not in payload
        assert set(payload) == {"type", "target_language", "source_language", "audio_format"}
    else:
        assert payload["interim_captions"] is interim_state


@pytest.fixture
def ws_harness(auth_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch) -> AuthHarness:
    auth_harness.register()
    auth_harness.login()
    fake_service = SimpleNamespace(
        transcribe=AsyncMock(
            return_value=TranscriptionResponse(text="Hello", detected_language="en")
        ),
        translate=AsyncMock(
            return_value=TranslationResponse(
                original_text="Hello", translated_text="Bonjour", target_language="fr"
            )
        ),
    )

    @asynccontextmanager
    async def fake_context(_settings, _provider_slots=None):
        yield fake_service

    monkeypatch.setattr("app.ws.translate.ai_service_context", fake_context)
    auth_harness.ws_service = fake_service
    return auth_harness


def test_authenticated_connection_and_start(ws_harness: AuthHarness) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        assert socket.receive_json() == {
            "type": "ready",
            "target_language": "fr",
            "source_language": None,
            "audio_format": "wav",
        }
        socket.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000


@pytest.mark.parametrize("target_language", list(LANGUAGE_NAMES))
def test_websocket_accepts_each_target_language(ws_harness: AuthHarness, target_language: str) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "target_language": target_language})
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        assert ready["target_language"] == target_language
        socket.send_json({"type": "stop"})


def test_unauthenticated_and_url_token_rejected(auth_harness: AuthHarness) -> None:
    with pytest.raises(WebSocketDisconnect) as denied:
        with auth_harness.client.websocket_connect(
            "/ws/translate?token=untrusted", headers=ORIGIN
        ):
            pass
    assert denied.value.code == 1008


def test_disallowed_or_missing_origin_rejected(ws_harness: AuthHarness) -> None:
    for headers in ({"origin": "https://attacker.example"}, {}):
        with pytest.raises(WebSocketDisconnect) as denied:
            with ws_harness.client.websocket_connect("/ws/translate", headers=headers):
                pass
        assert denied.value.code == 1008


def test_valid_audio_processing(ws_harness: AuthHarness) -> None:
    data = wav_chunk()
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(data)
        assert socket.receive_json() == {"type": "processing", "chunk_id": 1}
        result = socket.receive_json()
        assert result["type"] == "result"
        assert result["chunk_id"] == 1
        assert result["original"] == "Hello"
        assert result["translated"] == "Bonjour"
        assert result["detected_language"] == "en"
        assert result["language_detection_source"] == "stt"
        assert result["target_language"] == "fr"
        assert result["processing_time_ms"] >= 0
        assert 0 <= result["transcription_time_ms"] <= result["processing_time_ms"]
        assert 0 <= result["translation_time_ms"] <= result["processing_time_ms"]
    ws_harness.ws_service.transcribe.assert_awaited_once_with(data, "audio.wav")
    ws_harness.ws_service.translate.assert_awaited_once_with("Hello", "fr", source_language="en")


def test_pipeline_debug_timings_do_not_log_speech(ws_harness: AuthHarness, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.ws.translate"):
        with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
            socket.send_json(START)
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(wav_chunk())
            assert socket.receive_json()["type"] == "processing"
            assert socket.receive_json()["type"] == "result"
            socket.send_json({"type": "stop"})
    messages = "\n".join(record.getMessage() for record in caplog.records if record.name == "app.ws.translate")
    assert "WebSocket audio accepted chunk_id=1" in messages
    assert "WebSocket result sent chunk_id=1" in messages
    assert "Hello" not in messages
    assert "Bonjour" not in messages


def test_opt_in_speech_audio_preserves_browser_result_contract(ws_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    ws_harness.client.app.state.settings.azure_speech_key = SecretStr("test-only")
    ws_harness.client.app.state.settings.azure_speech_region = "eastus"
    ws_harness.client.app.state.settings.azure_speech_endpoint = "https://test-resource.cognitiveservices.azure.com"
    ws_harness.client.app.state.settings.azure_tts_enabled = True
    async def fake_speech(text, language, _settings):
        assert (text, language) == ("Bonjour", "fr")
        return wav_chunk()

    monkeypatch.setattr("app.ws.translate.synthesize_wav", fake_speech)
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "synthesize_speech": True})
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        result = socket.receive_json()
        assert result["type"] == "result"
        assert "audio_base64" not in result
        speech = socket.receive_json()
        assert speech["type"] == "speech_audio"
        assert speech["chunk_id"] == result["chunk_id"]
        assert base64.b64decode(speech["audio_base64"]) == wav_chunk()
        assert speech["preparation_time_ms"] >= 0


def test_opt_in_speech_failure_has_no_audio(ws_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.tts import TTSError
    ws_harness.client.app.state.settings.azure_speech_key = SecretStr("test-only")
    ws_harness.client.app.state.settings.azure_speech_region = "eastus"
    ws_harness.client.app.state.settings.azure_speech_endpoint = "https://test-resource.cognitiveservices.azure.com"
    ws_harness.client.app.state.settings.azure_tts_enabled = True

    async def unavailable(*_args):
        raise TTSError("provider details")

    monkeypatch.setattr("app.ws.translate.synthesize_wav", unavailable)
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "synthesize_speech": True})
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
        speech_error = socket.receive_json()
        assert speech_error == {"type": "speech_error", "chunk_id": 1,
                                "code": "speech_unavailable", "message": "Translated speech is unavailable"}


def test_opt_in_speech_requires_configuration_before_recording(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.azure_speech_key = None
    ws_harness.client.app.state.settings.azure_speech_region = None
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "synthesize_speech": True})
        assert socket.receive_json() == {"type": "error", "code": "speech_unavailable",
                                         "message": "Speech service is not configured", "recoverable": True}
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"


def test_websocket_reports_separate_mocked_stage_and_client_latency(ws_harness: AuthHarness) -> None:
    async def transcribe_with_delay(*_args):
        await asyncio.sleep(0.02)
        return TranscriptionResponse(text="Hello", detected_language="en")

    async def translate_with_delay(*_args, **_kwargs):
        await asyncio.sleep(0.02)
        return TranslationResponse(original_text="Hello", translated_text="Bonjour", target_language="fr")

    ws_harness.ws_service.transcribe.side_effect = transcribe_with_delay
    ws_harness.ws_service.translate.side_effect = translate_with_delay
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"
        sent_at = perf_counter()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        result = socket.receive_json()
        client_response_ms = int((perf_counter() - sent_at) * 1000)
        assert result["type"] == "result"
        assert result["transcription_time_ms"] >= 15
        assert result["translation_time_ms"] >= 15
        assert result["processing_time_ms"] >= 30
        assert client_response_ms >= result["processing_time_ms"]


def test_optional_source_language_passed_to_transcription(ws_harness: AuthHarness) -> None:
    data = wav_chunk()
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "source_language": "Hindi"})
        assert socket.receive_json()["source_language"] == "hi"
        socket.send_bytes(data)
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
    ws_harness.ws_service.transcribe.assert_awaited_once_with(data, "audio.wav", "hi")
    ws_harness.ws_service.translate.assert_awaited_once_with("Hello", "fr", source_language="hi")


def test_invalid_audio_then_valid_audio(ws_harness: AuthHarness) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(b"not a complete wav")
        assert socket.receive_json() == {
            "type": "error",
            "code": "invalid_audio",
            "message": "Invalid or incomplete WAV chunk",
            "recoverable": True,
        }
        socket.send_bytes(wav_chunk())
        assert socket.receive_json() == {"type": "processing", "chunk_id": 1}
        assert socket.receive_json()["type"] == "result"


def test_oversized_audio_rejected(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.ws_max_audio_bytes = 128
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        error = socket.receive_json()
        assert error["code"] == "audio_too_large"
        assert error["recoverable"] is True
    ws_harness.ws_service.transcribe.assert_not_awaited()


def test_control_message_limit_and_chunk_limit(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.ws_max_control_bytes = 128
    ws_harness.client.app.state.settings.ws_max_chunks = 1
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_text(" " * 129)
        assert socket.receive_json()["code"] == "invalid_message"
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["code"] == "chunk_limit"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000


def test_idle_connection_closes(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.ws_idle_timeout_seconds = 0.01
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        assert socket.receive_json()["code"] == "idle_timeout"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000


def test_unsupported_language_and_format_rejected(ws_harness: AuthHarness) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "target_language": "xx"})
        assert socket.receive_json()["code"] == "unsupported_language"
        socket.send_json({**START, "audio_format": "webm"})
        assert socket.receive_json()["code"] == "unsupported_audio_format"
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"


def test_malformed_controls_and_audio_before_start(ws_harness: AuthHarness) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_text("{bad json")
        assert socket.receive_json()["code"] == "invalid_message"
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["code"] == "invalid_state"
        socket.send_json({**START, "user_id": "client-supplied"})
        assert socket.receive_json()["code"] == "invalid_start"
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"
        socket.send_json(START)
        assert socket.receive_json()["code"] == "invalid_state"


def test_provider_timeout_is_recoverable(ws_harness: AuthHarness) -> None:
    ws_harness.ws_service.transcribe.side_effect = AIProviderTimeout("internal details")
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        error = socket.receive_json()
        assert error == {
            "type": "error",
            "code": "provider_timeout",
            "message": "AI provider timed out",
            "recoverable": True,
        }


def test_translation_failure_is_recoverable(ws_harness: AuthHarness) -> None:
    ws_harness.ws_service.translate.side_effect = AIProviderFailure("internal details")
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        error = socket.receive_json()
        assert error["code"] == "provider_error"
        assert error["message"] == "AI processing failed"
        assert error["recoverable"] is True
        assert error["original"] == "Hello"
        assert error["detected_language"] == "en"
        assert error["language_detection_source"] == "stt"
        assert error["chunk_id"] == 1


@pytest.mark.parametrize("language,text,target", [
    ("en", "Hello", "hi"), ("hi", "नमस्ते", "en"), ("mr", "नमस्कार", "en"),
])
def test_auto_detect_uses_stt_metadata_per_phrase(ws_harness: AuthHarness, language, text, target) -> None:
    ws_harness.ws_service.transcribe.return_value = TranscriptionResponse(text=text, detected_language=language)
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "target_language": target})
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        result = socket.receive_json()
        assert result["original"] == text
        assert result["detected_language"] == language
        assert result["language_detection_source"] == "stt"
    ws_harness.ws_service.transcribe.assert_awaited_once_with(wav_chunk(), "audio.wav")
    ws_harness.ws_service.translate.assert_awaited_once_with(text, target, source_language=language)


def test_auto_detect_can_change_between_consecutive_phrases(ws_harness: AuthHarness) -> None:
    ws_harness.ws_service.transcribe.side_effect = [
        TranscriptionResponse(text="Hello", detected_language="en"),
        TranscriptionResponse(text="नमस्कार", detected_language="mr"),
    ]
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "target_language": "hi"})
        socket.receive_json()
        for expected in ("en", "mr"):
            socket.send_bytes(wav_chunk())
            assert socket.receive_json()["type"] == "processing"
            result = socket.receive_json()
            assert result["detected_language"] == expected
    assert ws_harness.ws_service.translate.await_args_list[0].kwargs["source_language"] == "en"
    assert ws_harness.ws_service.translate.await_args_list[1].kwargs["source_language"] == "mr"


@pytest.mark.parametrize("raw", [None, "xx"])
def test_missing_or_unsupported_detection_stays_unknown(ws_harness: AuthHarness, raw) -> None:
    ws_harness.ws_service.transcribe.return_value = TranscriptionResponse(text="Hello", detected_language=raw)
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        socket.receive_json()
        result = socket.receive_json()
        assert result["detected_language"] is None
        assert result["language_detection_source"] == "unknown"
    ws_harness.ws_service.translate.assert_awaited_once_with("Hello", "fr", source_language=None)


def test_same_language_detection_skips_llm_and_preserves_phrase(ws_harness: AuthHarness) -> None:
    ws_harness.ws_service.transcribe.return_value = TranscriptionResponse(text="नमस्ते", detected_language="hi")
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "target_language": "hi"})
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        socket.receive_json()
        result = socket.receive_json()
        assert result["original"] == result["translated"] == "नमस्ते"
        assert result["translation_time_ms"] == 0
    ws_harness.ws_service.translate.assert_not_awaited()


def test_processing_timeout_is_recoverable(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.settings.ws_processing_timeout_seconds = 0.01

    async def slow_transcription(*_args):
        await asyncio.sleep(0.1)

    ws_harness.ws_service.transcribe.side_effect = slow_transcription
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        error = socket.receive_json()
        assert error["code"] == "processing_timeout"
        assert error["recoverable"] is True


def test_silent_chunk_returns_recoverable_error(ws_harness: AuthHarness) -> None:
    ws_harness.ws_service.transcribe.side_effect = AINoSpeechError("no speech")
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        error = socket.receive_json()
        assert error["code"] == "no_speech"
        assert error["recoverable"] is True


def test_stop_closes_connection(ws_harness: AuthHarness) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000


@pytest.mark.parametrize("change", ["revoke", "expire"])
def test_revoked_or_expired_session_closes_active_socket(ws_harness: AuthHarness, change: str) -> None:
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()

        async def invalidate() -> None:
            async with ws_harness.sessionmaker() as db:
                session = await db.scalar(select(UserSession))
                assert session is not None
                if change == "revoke":
                    session.revoked_at = datetime.now(timezone.utc)
                else:
                    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()

        asyncio.run(invalidate())
        socket.send_bytes(wav_chunk())
        error = socket.receive_json()
        assert error["code"] == "session_invalid"
        assert error["recoverable"] is False
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1008
    ws_harness.ws_service.transcribe.assert_not_awaited()


def test_revocation_during_transcription_prevents_translation(ws_harness: AuthHarness) -> None:
    async def revoke_then_transcribe(*_args):
        async with ws_harness.sessionmaker() as db:
            session = await db.scalar(select(UserSession))
            assert session is not None
            session.revoked_at = datetime.now(timezone.utc)
            await db.commit()
        return TranscriptionResponse(text="Hello", detected_language="en")

    ws_harness.ws_service.transcribe.side_effect = revoke_then_transcribe
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["code"] == "session_invalid"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1008
    ws_harness.ws_service.translate.assert_not_awaited()


def test_multiple_chunks_preserve_order(ws_harness: AuthHarness) -> None:
    data = wav_chunk()
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json(START)
        socket.receive_json()
        for _ in range(3):
            socket.send_bytes(data)
        sequence = [socket.receive_json() for _ in range(6)]
        assert [(message["type"], message["chunk_id"]) for message in sequence] == [
            ("processing", 1),
            ("result", 1),
            ("processing", 2),
            ("result", 2),
            ("processing", 3),
            ("result", 3),
        ]
    assert ws_harness.ws_service.transcribe.await_count == 3
    assert ws_harness.ws_service.translate.await_count == 3


def test_per_user_connection_limit(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.websocket_connections.max_per_user = 1
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as first:
        with pytest.raises(WebSocketDisconnect) as denied:
            with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN):
                pass
        assert denied.value.code == 1013
        first.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect):
            first.receive_json()
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as later:
        later.send_json(START)
        assert later.receive_json()["type"] == "ready"


def test_disconnect_releases_connection_slot(ws_harness: AuthHarness) -> None:
    ws_harness.client.app.state.websocket_connections.max_per_user = 1
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as first:
        first.send_json(START)
        assert first.receive_json()["type"] == "ready"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as second:
        second.send_json(START)
        assert second.receive_json()["type"] == "ready"
