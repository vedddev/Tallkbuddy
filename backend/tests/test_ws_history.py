"""Explicit WebSocket history saving and retry behavior."""

import asyncio
import importlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketDisconnect

from app.ai.service import AIProviderFailure
from app.db.models import TranslationMessage
from tests.test_history import create_session, csrf_headers, enable_history
from tests.test_websocket import ORIGIN, START, wav_chunk, ws_harness  # noqa: F401 - fixture
from tests.test_auth import AuthHarness, auth_harness  # noqa: F401 - fixture dependency


def count_messages(harness: AuthHarness) -> int:
    async def count() -> int:
        async with harness.sessionmaker() as db:
            return await db.scalar(select(func.count()).select_from(TranslationMessage))

    return asyncio.run(count())


def test_websocket_history_disabled_by_default(ws_harness: AuthHarness) -> None:
    session_id = create_session(ws_harness)
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "save_history": True, "session_id": session_id})
        error = socket.receive_json()
        assert error["code"] == "history_disabled"
        assert error["recoverable"] is True
        socket.send_json(START)
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"
    assert count_messages(ws_harness) == 0


def test_websocket_save_and_retry_return_one_message(ws_harness: AuthHarness) -> None:
    enable_history(ws_harness)
    session_id = create_session(ws_harness)
    request_id = str(uuid4())
    audio = wav_chunk()
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "save_history": True, "session_id": session_id})
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(audio)
        assert socket.receive_json()["code"] == "missing_request_id"
        socket.send_json({"type": "chunk", "request_id": request_id})
        socket.send_bytes(audio)
        assert socket.receive_json() == {"type": "processing", "chunk_id": 1}
        first = socket.receive_json()
        assert first["type"] == "result"
        assert first["saved"] is True
        assert first["message_id"]
        socket.send_json({"type": "chunk", "request_id": request_id})
        socket.send_bytes(audio)
        assert socket.receive_json() == {"type": "processing", "chunk_id": 2}
        second = socket.receive_json()
        assert second["message_id"] == first["message_id"]
        assert second["original"] == first["original"]
        socket.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000
    assert count_messages(ws_harness) == 1
    assert ws_harness.ws_service.transcribe.await_count == 1
    assert ws_harness.ws_service.translate.await_count == 1


def test_websocket_conflicting_retry_rejected(ws_harness: AuthHarness) -> None:
    enable_history(ws_harness)
    session_id = create_session(ws_harness)
    request_id = str(uuid4())
    first_audio = wav_chunk()
    second_audio = first_audio[:-2] + b"\x02\x00"
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "save_history": True, "session_id": session_id})
        socket.receive_json()
        socket.send_json({"type": "chunk", "request_id": request_id})
        socket.send_bytes(first_audio)
        socket.receive_json()
        assert socket.receive_json()["type"] == "result"
        socket.send_json({"type": "chunk", "request_id": request_id})
        socket.send_bytes(second_audio)
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["code"] == "idempotency_conflict"
    assert count_messages(ws_harness) == 1
    assert ws_harness.ws_service.transcribe.await_count == 1


def test_disabling_history_during_socket_prevents_next_save(ws_harness: AuthHarness) -> None:
    enable_history(ws_harness)
    session_id = create_session(ws_harness)
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "save_history": True, "session_id": session_id})
        socket.receive_json()
        socket.send_json({"type": "chunk", "request_id": str(uuid4())})
        socket.send_bytes(wav_chunk())
        socket.receive_json()
        assert socket.receive_json()["saved"] is True
        disabled = ws_harness.client.patch(
            "/api/preferences", json={"save_history_enabled": False}, headers=csrf_headers(ws_harness)
        )
        assert disabled.status_code == 200
        socket.send_json({"type": "chunk", "request_id": str(uuid4())})
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["code"] == "history_disabled"
    assert count_messages(ws_harness) == 1
    assert ws_harness.ws_service.transcribe.await_count == 1


def test_failed_websocket_translation_does_not_save(ws_harness: AuthHarness) -> None:
    enable_history(ws_harness)
    session_id = create_session(ws_harness)
    ws_harness.ws_service.translate.side_effect = AIProviderFailure("provider failed")
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "save_history": True, "session_id": session_id})
        socket.receive_json()
        socket.send_json({"type": "chunk", "request_id": str(uuid4())})
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["code"] == "provider_error"
    assert count_messages(ws_harness) == 0


def test_cached_retry_database_failure_is_generic_and_closes(
    ws_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_history(ws_harness)
    session_id = create_session(ws_harness)
    request_id = str(uuid4())
    ws_module = importlib.import_module("app.ws.translate")
    original_check = ws_module._active_user_id
    with ws_harness.client.websocket_connect("/ws/translate", headers=ORIGIN) as socket:
        socket.send_json({**START, "save_history": True, "session_id": session_id})
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"type": "chunk", "request_id": request_id})
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        assert socket.receive_json()["type"] == "result"

        checks = 0

        async def failing_cached_check(db, token):
            nonlocal checks
            checks += 1
            if checks == 3:
                raise SQLAlchemyError("private database details")
            return await original_check(db, token)

        monkeypatch.setattr(ws_module, "_active_user_id", failing_cached_check)
        socket.send_json({"type": "chunk", "request_id": request_id})
        socket.send_bytes(wav_chunk())
        assert socket.receive_json()["type"] == "processing"
        error = socket.receive_json()
        assert error == {
            "type": "error", "code": "session_check_failed",
            "message": "Session check failed", "recoverable": False,
        }
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1011
