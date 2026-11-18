"""Opt-in integration test against a dedicated PostgreSQL test database only."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.schemas import TranslationResponse
from app.ai.service import get_ai_service
from app.auth.security import CSRF_COOKIE_NAME
from app.core.config import Settings
from app.db.models import User
from app.db.session import get_db_session
from app.main import create_app


@pytest.mark.postgres
def test_dedicated_postgres_auth_history_and_rollback() -> None:
    raw_test_url = os.getenv("TEST_DATABASE_URL")
    if not raw_test_url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    test_url = make_url(raw_test_url)
    app_url = make_url(Settings().database_url or "postgresql+asyncpg://localhost/unused")
    if (
        test_url.drivername != "postgresql+asyncpg"
        or not test_url.database
        or "test" not in test_url.database.lower()
        or test_url.database == app_url.database
    ):
        pytest.fail("TEST_DATABASE_URL must point to a separate PostgreSQL test database")

    engine = create_async_engine(test_url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def verify_target() -> None:
        async with engine.connect() as db:
            actual = await db.scalar(text("SELECT current_database()"))
            assert actual == test_url.database

    asyncio.run(verify_target())
    backend_dir = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": raw_test_url},
        capture_output=True,
        text=True,
        check=True,
    )

    app = create_app(Settings(app_env="test", database_url=raw_test_url))

    async def isolated_db():
        async with maker() as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    service = SimpleNamespace(
        translate=AsyncMock(
            return_value=TranslationResponse(
                original_text="Hello", translated_text="Bonjour", target_language="fr"
            )
        )
    )

    async def fake_ai():
        yield service

    app.dependency_overrides[get_db_session] = isolated_db
    app.dependency_overrides[get_ai_service] = fake_ai
    created_users: list[UUID] = []
    suffix = uuid4().hex

    def csrf(client: TestClient) -> dict[str, str]:
        return {"X-CSRF-Token": client.cookies[CSRF_COOKIE_NAME]}

    try:
        with TestClient(app) as client:
            for index in (1, 2):
                email = f"phase7-{suffix}-{index}@example.invalid"
                register = client.post(
                    "/api/auth/register",
                    json={"name": "Integration User", "email": email, "password": "correct-horse-battery-staple"},
                )
                assert register.status_code == 201, register.text
                created_users.append(UUID(register.json()["id"]))
                assert client.post(
                    "/api/auth/register",
                    json={"name": "Integration User", "email": email, "password": "correct-horse-battery-staple"},
                ).status_code == 409
                login = client.post(
                    "/api/auth/login", json={"email": email, "password": "correct-horse-battery-staple"}
                )
                assert login.status_code == 200, login.text
                assert client.get("/api/auth/me").status_code == 200
                if index == 1:
                    pref = client.patch(
                        "/api/preferences", json={"target_language": "fr", "save_history_enabled": True}, headers=csrf(client)
                    )
                    assert pref.status_code == 200
                    session = client.post(
                        "/api/translation-sessions", json={"title": "Phase 7"}, headers=csrf(client)
                    )
                    assert session.status_code == 201
                    session_id = session.json()["id"]
                    request_id = str(uuid4())
                    payload = {"text": "Hello", "target_language": "fr", "save_history": True, "session_id": session_id}
                    headers = {**csrf(client), "Idempotency-Key": request_id}
                    first = client.post("/api/ai/translate", json=payload, headers=headers)
                    second = client.post("/api/ai/translate", json=payload, headers=headers)
                    assert first.status_code == second.status_code == 200
                    assert first.json()["message_id"] == second.json()["message_id"]
                    assert service.translate.await_count == 1
                    detail = client.get(f"/api/history/{session_id}")
                    assert detail.status_code == 200
                    assert detail.json()["messages"]["total"] == 1
                    assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 200
                    assert client.get("/api/auth/me").status_code == 401
                else:
                    assert client.get(f"/api/history/{session_id}").status_code == 404
                    assert client.delete(f"/api/history/{session_id}", headers=csrf(client)).status_code == 404
                    assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 200

            email = f"phase7-{suffix}-1@example.invalid"
            assert client.post(
                "/api/auth/login", json={"email": email, "password": "correct-horse-battery-staple"}
            ).status_code == 200
            assert client.delete(f"/api/history/{session_id}", headers=csrf(client)).status_code == 204
            assert client.get(f"/api/history/{session_id}").status_code == 404
            assert client.get("/api/preferences").json()["save_history_enabled"] is True
    finally:
        async def cleanup() -> None:
            async with maker() as db:
                await db.execute(delete(User).where(User.id.in_(created_users)))
                await db.commit()
            await engine.dispose()

        asyncio.run(cleanup())
