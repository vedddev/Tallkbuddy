"""Owned history, preferences, and explicit REST persistence tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.ai.schemas import TranscriptionResponse, TranslationResponse
from app.ai.service import AIProviderFailure, get_ai_service
from app.auth.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.db.models import TranslationMessage, TranslationSession, UserPreference
from tests.test_ai import WAV_AUDIO
from tests.test_auth import AuthHarness, auth_harness  # noqa: F401 - isolated database fixture


def csrf_headers(harness: AuthHarness, request_id: UUID | None = None) -> dict[str, str]:
    headers = {CSRF_HEADER_NAME: harness.client.cookies[CSRF_COOKIE_NAME]}
    if request_id is not None:
        headers["Idempotency-Key"] = str(request_id)
    return headers


def create_session(harness: AuthHarness, target: str = "fr") -> str:
    response = harness.client.post(
        "/api/translation-sessions",
        json={"source_language": "en", "target_language": target, "title": "Conversation"},
        headers=csrf_headers(harness),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def enable_history(harness: AuthHarness) -> None:
    response = harness.client.patch(
        "/api/preferences",
        json={"save_history_enabled": True},
        headers=csrf_headers(harness),
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def logged_in(auth_harness: AuthHarness) -> AuthHarness:
    auth_harness.register()
    auth_harness.login()
    return auth_harness


@pytest.fixture
def ai_harness(logged_in: AuthHarness) -> AuthHarness:
    fake_service = SimpleNamespace(
        transcribe=AsyncMock(return_value=TranscriptionResponse(text="Hello", detected_language="en")),
        translate=AsyncMock(
            return_value=TranslationResponse(
                original_text="Hello", translated_text="Bonjour", target_language="fr"
            )
        ),
    )
    logged_in.client.app.dependency_overrides[get_ai_service] = lambda: fake_service
    logged_in.ai_service = fake_service
    return logged_in


def test_preferences_default_and_update_once(logged_in: AuthHarness) -> None:
    response = logged_in.client.get("/api/preferences")
    assert response.status_code == 200
    assert response.json() == {
        "source_language": "auto",
        "target_language": "en",
        "speech_rate": 1.0,
        "save_history_enabled": False,
    }
    response = logged_in.client.patch(
        "/api/preferences",
        json={"source_language": "Hindi", "target_language": "French", "speech_rate": 1.25},
        headers=csrf_headers(logged_in),
    )
    assert response.status_code == 200
    assert response.json()["source_language"] == "hi"
    assert response.json()["target_language"] == "fr"
    logged_in.client.patch(
        "/api/preferences", json={"save_history_enabled": True}, headers=csrf_headers(logged_in)
    )

    async def count_preferences() -> int:
        async with logged_in.sessionmaker() as db:
            return await db.scalar(select(func.count()).select_from(UserPreference))

    assert asyncio.run(count_preferences()) == 1


def test_new_language_preferences_and_session_target(logged_in: AuthHarness) -> None:
    response = logged_in.client.patch(
        "/api/preferences",
        json={"source_language": "ja", "target_language": "zh-CN"},
        headers=csrf_headers(logged_in),
    )
    assert response.status_code == 200
    assert response.json()["source_language"] == "ja"
    assert response.json()["target_language"] == "zh-CN"
    session_id = create_session(logged_in, target="zh-CN")
    assert UUID(session_id)


@pytest.mark.parametrize(
    "payload",
    [
        {"source_language": "xx"},
        {"target_language": "Klingon"},
        {"speech_rate": 0.1},
        {"speech_rate": 3.0},
        {"speech_rate": None},
        {},
    ],
)
def test_preference_validation(logged_in: AuthHarness, payload: dict) -> None:
    response = logged_in.client.patch(
        "/api/preferences", json=payload, headers=csrf_headers(logged_in)
    )
    assert response.status_code == 422


def test_session_creation_update_end_and_timezone(logged_in: AuthHarness) -> None:
    session_id = create_session(logged_in)
    detail = logged_in.client.get(f"/api/history/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["session"]["started_at"].endswith("Z")
    renamed = logged_in.client.patch(
        f"/api/translation-sessions/{session_id}",
        json={"title": "  Meeting  "},
        headers=csrf_headers(logged_in),
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Meeting"
    ended = logged_in.client.post(
        f"/api/translation-sessions/{session_id}/end", headers=csrf_headers(logged_in)
    )
    assert ended.status_code == 200
    assert ended.json()["ended_at"] is not None
    assert ended.json()["ended_at"].endswith("Z")
    again = logged_in.client.post(
        f"/api/translation-sessions/{session_id}/end", headers=csrf_headers(logged_in)
    )
    assert again.json()["ended_at"] == ended.json()["ended_at"]


def test_history_pagination_sorting_and_deletion(logged_in: AuthHarness) -> None:
    ids = [create_session(logged_in) for _ in range(3)]
    page1 = logged_in.client.get("/api/history?limit=2&offset=0&order=oldest")
    page2 = logged_in.client.get("/api/history?limit=2&offset=2&order=oldest")
    assert page1.status_code == page2.status_code == 200
    assert page1.json()["total"] == 3
    assert page1.json()["limit"] == 2
    assert len(page1.json()["items"]) == 2
    assert len(page2.json()["items"]) == 1
    assert {item["id"] for item in page1.json()["items"] + page2.json()["items"]} == set(ids)

    deleted = logged_in.client.delete(f"/api/history/{ids[0]}", headers=csrf_headers(logged_in))
    assert deleted.status_code == 204
    assert logged_in.client.get(f"/api/history/{ids[0]}").status_code == 404
    cleared = logged_in.client.delete("/api/history", headers=csrf_headers(logged_in))
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted_sessions": 2}
    assert logged_in.client.get("/api/history").json()["total"] == 0


def test_cross_user_history_and_session_isolation(logged_in: AuthHarness) -> None:
    session_id = create_session(logged_in)
    other = {"name": "Other User", "email": "other@example.com", "password": "other-long-password"}
    assert logged_in.client.post("/api/auth/register", json=other).status_code == 201
    assert logged_in.client.post(
        "/api/auth/login", json={"email": other["email"], "password": other["password"]}
    ).status_code == 200
    assert logged_in.client.get("/api/history").json()["total"] == 0
    assert logged_in.client.get(f"/api/history/{session_id}").status_code == 404
    assert logged_in.client.patch(
        f"/api/translation-sessions/{session_id}",
        json={"title": "Stolen"}, headers=csrf_headers(logged_in),
    ).status_code == 404
    assert logged_in.client.post(
        f"/api/translation-sessions/{session_id}/end", headers=csrf_headers(logged_in)
    ).status_code == 404
    assert logged_in.client.delete(
        f"/api/history/{session_id}", headers=csrf_headers(logged_in)
    ).status_code == 404
    assert logged_in.client.delete("/api/history", headers=csrf_headers(logged_in)).json() == {
        "deleted_sessions": 0
    }


def test_unauthorized_csrf_and_bad_session_id(auth_harness: AuthHarness) -> None:
    assert auth_harness.client.get("/api/history").status_code == 401
    assert auth_harness.client.get("/api/preferences").status_code == 401
    assert auth_harness.client.post("/api/translation-sessions", json={}).status_code == 401
    auth_harness.register()
    auth_harness.login()
    assert auth_harness.client.patch("/api/preferences", json={"speech_rate": 1.2}).status_code == 403
    assert auth_harness.client.delete("/api/history").status_code == 403
    assert auth_harness.client.get("/api/history/not-a-uuid").status_code == 422
    assert auth_harness.client.get("/api/history?limit=101").status_code == 422


def test_history_disabled_by_default_and_no_auto_save(ai_harness: AuthHarness) -> None:
    session_id = create_session(ai_harness)
    no_save = ai_harness.client.post(
        "/api/ai/translate",
        json={"text": "Hello", "target_language": "fr", "session_id": session_id},
        headers=csrf_headers(ai_harness),
    )
    assert no_save.status_code == 200
    assert "saved" not in no_save.json()
    attempted = ai_harness.client.post(
        "/api/ai/translate",
        json={"text": "Hello", "target_language": "fr", "save_history": True, "session_id": session_id},
        headers=csrf_headers(ai_harness, uuid4()),
    )
    assert attempted.status_code == 409
    assert ai_harness.client.get(f"/api/history/{session_id}").json()["messages"]["total"] == 0


def test_rest_text_save_retry_and_conflict(ai_harness: AuthHarness) -> None:
    enable_history(ai_harness)
    session_id = create_session(ai_harness)
    request_id = uuid4()
    payload = {"text": "Hello", "target_language": "fr", "save_history": True, "session_id": session_id}
    first = ai_harness.client.post(
        "/api/ai/translate", json=payload, headers=csrf_headers(ai_harness, request_id)
    )
    second = ai_harness.client.post(
        "/api/ai/translate", json=payload, headers=csrf_headers(ai_harness, request_id)
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["saved"] is True
    assert first.json()["message_id"]
    assert ai_harness.ai_service.translate.await_count == 1
    detail = ai_harness.client.get(f"/api/history/{session_id}?limit=1")
    assert detail.json()["messages"]["total"] == 1
    assert detail.json()["messages"]["items"][0]["original_text"] == "Hello"
    assert "idempotency_key" not in detail.text
    conflict = ai_harness.client.post(
        "/api/ai/translate", json={**payload, "text": "Different"},
        headers=csrf_headers(ai_harness, request_id),
    )
    assert conflict.status_code == 409
    assert ai_harness.ai_service.translate.await_count == 1


def test_rest_speech_save_retry_without_audio_storage(ai_harness: AuthHarness) -> None:
    enable_history(ai_harness)
    session_id = create_session(ai_harness)
    request_id = uuid4()
    form = {"target_language": "fr", "save_history": "true", "session_id": session_id}
    first = ai_harness.client.post(
        "/api/ai/speech-translate", data=form,
        files={"audio": ("sample.wav", WAV_AUDIO, "audio/wav")},
        headers=csrf_headers(ai_harness, request_id),
    )
    second = ai_harness.client.post(
        "/api/ai/speech-translate", data=form,
        files={"audio": ("sample.wav", WAV_AUDIO, "audio/wav")},
        headers=csrf_headers(ai_harness, request_id),
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert ai_harness.ai_service.transcribe.await_count == 1
    assert ai_harness.ai_service.translate.await_count == 1
    assert ai_harness.client.get(f"/api/history/{session_id}").json()["messages"]["total"] == 1
    assert not hasattr(TranslationMessage, "audio")


def test_failed_translation_is_not_saved(ai_harness: AuthHarness) -> None:
    enable_history(ai_harness)
    session_id = create_session(ai_harness)
    ai_harness.ai_service.translate.side_effect = AIProviderFailure("provider failed")
    response = ai_harness.client.post(
        "/api/ai/translate",
        json={"text": "Hello", "target_language": "fr", "save_history": True, "session_id": session_id},
        headers=csrf_headers(ai_harness, uuid4()),
    )
    assert response.status_code == 502
    assert ai_harness.client.get(f"/api/history/{session_id}").json()["messages"]["total"] == 0


def test_saving_requires_request_key_and_open_owned_session(ai_harness: AuthHarness) -> None:
    enable_history(ai_harness)
    session_id = create_session(ai_harness)
    payload = {"text": "Hello", "target_language": "fr", "save_history": True, "session_id": session_id}
    assert ai_harness.client.post(
        "/api/ai/translate", json=payload, headers=csrf_headers(ai_harness)
    ).status_code == 422
    assert ai_harness.client.post(
        "/api/ai/translate", json={**payload, "session_id": str(uuid4())},
        headers=csrf_headers(ai_harness, uuid4()),
    ).status_code == 404
    ai_harness.client.post(
        f"/api/translation-sessions/{session_id}/end", headers=csrf_headers(ai_harness)
    )
    assert ai_harness.client.post(
        "/api/ai/translate", json=payload, headers=csrf_headers(ai_harness, uuid4())
    ).status_code == 409


def test_message_pagination_and_session_delete_cascades(ai_harness: AuthHarness) -> None:
    enable_history(ai_harness)
    session_id = create_session(ai_harness)
    payload = {"text": "Hello", "target_language": "fr", "save_history": True, "session_id": session_id}
    for _ in range(3):
        assert ai_harness.client.post(
            "/api/ai/translate", json=payload, headers=csrf_headers(ai_harness, uuid4())
        ).status_code == 200
    page = ai_harness.client.get(f"/api/history/{session_id}?limit=2&offset=1&order=newest")
    assert page.status_code == 200
    assert page.json()["messages"]["total"] == 3
    assert len(page.json()["messages"]["items"]) == 2
    assert ai_harness.client.delete(
        f"/api/history/{session_id}", headers=csrf_headers(ai_harness)
    ).status_code == 204

    async def count_orphans() -> int:
        async with ai_harness.sessionmaker() as db:
            return await db.scalar(select(func.count()).select_from(TranslationMessage))

    assert asyncio.run(count_orphans()) == 0


def test_database_failure_is_generic(logged_in: AuthHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failed_list(*_args):
        raise OperationalError("SELECT private", {}, Exception("private connection details"))

    monkeypatch.setattr("app.api.history.list_sessions", failed_list)
    response = logged_in.client.get("/api/history")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private" not in response.text
