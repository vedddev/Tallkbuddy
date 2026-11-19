"""Authenticated, sequential WebSocket translation protocol tests."""

import asyncio
import base64
import io
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
from app.ai.service import AINoSpeechError, AIProviderFailure, AIProviderTimeout
from app.db.models import UserSession
from app.ws.protocol import ResultMessage
from app.ws.translate import _send
from tests.test_auth import AuthHarness, auth_harness  # noqa: F401 - isolated DB fixture


ORIGIN = {"origin": "http://testserver"}
START = {"type": "start", "target_language": "fr", "audio_format": "wav"}


def wav_chunk() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b"\x01\x00" * 1600)
    return buffer.getvalue()


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
        assert result["target_language"] == "fr"
        assert result["processing_time_ms"] >= 0
        assert 0 <= result["transcription_time_ms"] <= result["processing_time_ms"]
        assert 0 <= result["translation_time_ms"] <= result["processing_time_ms"]
    ws_harness.ws_service.transcribe.assert_awaited_once_with(data, "audio.wav")
    ws_harness.ws_service.translate.assert_awaited_once_with("Hello", "fr")


def test_opt_in_speech_audio_preserves_browser_result_contract(ws_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    ws_harness.client.app.state.settings.azure_speech_key = SecretStr("test-only")
    ws_harness.client.app.state.settings.azure_speech_region = "eastus"
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

    async def translate_with_delay(*_args):
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
