"""Fail-closed deployment settings without contacting a database or provider."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from app.ws.translate import _origin_allowed


PRODUCTION = {
    "app_env": "production",
    "public_origin": "https://talkbuddy.example",
    "cors_origins": ["https://talkbuddy.example"],
    "database_url": "postgresql+asyncpg://user:test-only@db.example/talkbuddy",
    "groq_api_key": "test-only-groq-key",
}


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**PRODUCTION, **overrides})


def test_valid_production_configuration_starts_without_opening_database() -> None:
    application = create_app(settings())
    with TestClient(application) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert application.state.settings.cookie_secure is True


@pytest.mark.parametrize(
    "override",
    [
        {"public_origin": None},
        {"public_origin": "http://talkbuddy.example"},
        {"public_origin": "https://localhost"},
        {"cors_origins": ["*"]},
        {"cors_origins": ["https://other.example"]},
        {"auth_cookie_secure": False},
        {"database_url": None},
        {"database_url": "sqlite:///test.db"},
        {"database_url": "postgresql+asyncpg://user:replace-with-password@db.example/talkbuddy"},
        {"groq_api_key": None},
        {"groq_api_key": "your_groq_api_key_here"},
        {"azure_speech_key": "test-only-azure", "azure_speech_region": None},
        {"azure_speech_key": None, "azure_speech_region": "eastus"},
    ],
)
def test_unsafe_production_configuration_fails_without_echoing_values(override: dict[str, object]) -> None:
    with pytest.raises(RuntimeError) as failed:
        create_app(settings(**override))
    assert "test-only" not in str(failed.value)
    assert "replace-with-password" not in str(failed.value)


def test_production_websocket_origin_uses_public_origin_instead_of_host() -> None:
    configured = settings()
    forged = SimpleNamespace(headers={"origin": "https://evil.example", "host": "evil.example"}, url=SimpleNamespace(scheme="wss"))
    trusted = SimpleNamespace(headers={"origin": "https://talkbuddy.example", "host": "backend.internal"}, url=SimpleNamespace(scheme="ws"))
    assert _origin_allowed(forged, configured) is False
    assert _origin_allowed(trusted, configured) is True


def test_production_http_origin_and_cors_reject_forged_host() -> None:
    application = create_app(settings())

    async def unused_database_session():
        # This test checks origin and request validation, not database access.
        yield object()

    application.dependency_overrides[get_db_session] = unused_database_session
    with TestClient(application) as client:
        forged = client.post(
            "/api/auth/register", json={},
            headers={"Host": "evil.example", "Origin": "https://evil.example"},
        )
        trusted = client.post(
            "/api/auth/register", json={},
            headers={"Host": "evil.example", "Origin": "https://talkbuddy.example"},
        )
        preflight = client.options(
            "/api/auth/register",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
    assert forged.status_code == 403
    assert trusted.status_code == 422
    assert preflight.status_code == 400
