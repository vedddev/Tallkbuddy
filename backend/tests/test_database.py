"""Database schema, session lifecycle, and health checks."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, ForeignKey, UniqueConstraint

from app.db import session as database_session
from app.core.config import Settings
from app.db.base import Base
from app.db.models import (  # noqa: F401 - imports register model metadata
    TranslationMessage,
    TranslationSession,
    User,
    UserPreference,
    UserSession,
)
from app.main import app


def test_model_tables_constraints_and_timestamps() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "user_sessions",
        "user_preferences",
        "translation_sessions",
        "translation_messages",
    }

    users = Base.metadata.tables["users"]
    assert users.c.id.primary_key
    assert users.c.email.unique is True
    assert users.c.email.index is True
    assert users.c.password_hash.nullable is False

    preferences = Base.metadata.tables["user_preferences"]
    assert any(
        isinstance(constraint, UniqueConstraint)
        and set(constraint.columns.keys()) == {"user_id"}
        for constraint in preferences.constraints
    )

    expected_foreign_keys = {
        "user_sessions": ("user_id", "users.id"),
        "user_preferences": ("user_id", "users.id"),
        "translation_sessions": ("user_id", "users.id"),
        "translation_messages": ("session_id", "translation_sessions.id"),
    }
    for table_name, (column_name, target) in expected_foreign_keys.items():
        table = Base.metadata.tables[table_name]
        foreign_key = next(iter(table.c[column_name].foreign_keys))
        assert isinstance(foreign_key, ForeignKey)
        assert foreign_key.target_fullname == target
        assert foreign_key.ondelete == "CASCADE"

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone is True


class FakeSession:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False
        self.rolled_back = False
        self.statements: list[str] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.closed = True

    async def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))
        if self.error is not None:
            raise self.error

    async def rollback(self) -> None:
        self.rolled_back = True


def test_database_session_closes_and_rolls_back_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(database_session, "get_sessionmaker", lambda: lambda: fake)

    async def exercise() -> None:
        dependency = database_session.get_db_session()
        assert await anext(dependency) is fake
        with pytest.raises(RuntimeError, match="request failed"):
            await dependency.athrow(RuntimeError("request failed"))

    asyncio.run(exercise())
    assert fake.rolled_back is True
    assert fake.closed is True


def test_engine_has_bounded_pool_and_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = object()

    def fake_create_engine(url: str, **options: object) -> object:
        captured.update(url=url, **options)
        return fake_engine

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test@localhost:5432/talkbuddy_test_db",
        database_pool_size=3,
        database_max_overflow=2,
        database_pool_timeout_seconds=4,
        database_command_timeout_seconds=9,
    )
    monkeypatch.setattr(database_session, "get_settings", lambda: settings)
    monkeypatch.setattr(database_session, "create_async_engine", fake_create_engine)
    database_session.get_engine.cache_clear()
    try:
        assert database_session.get_engine() is fake_engine
        assert captured["pool_size"] == 3
        assert captured["max_overflow"] == 2
        assert captured["pool_timeout"] == 4
        assert captured["connect_args"] == {"command_timeout": 9}
    finally:
        database_session.get_engine.cache_clear()


@pytest.mark.parametrize("path", ["/api/health/db", "/api/health/ready"])
def test_database_health_succeeds_with_available_session(path: str) -> None:
    fake = FakeSession()

    async def override_session():
        yield fake

    app.dependency_overrides[database_session.get_db_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get(path)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fake.statements == ["SELECT 1"]


@pytest.mark.parametrize("path", ["/api/health/db", "/api/health/ready"])
def test_database_health_hides_connection_error(path: str) -> None:
    fake = FakeSession(RuntimeError("private connection details"))

    async def override_session():
        yield fake

    app.dependency_overrides[database_session.get_db_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get(path)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private connection details" not in response.text


@pytest.mark.parametrize("path", ["/api/health/db", "/api/health/ready"])
def test_database_health_without_configuration_returns_503(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    def unavailable_sessionmaker() -> None:
        raise database_session.DatabaseConfigurationError("private database URL")

    monkeypatch.setattr(database_session, "get_sessionmaker", unavailable_sessionmaker)
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private database URL" not in response.text


def test_initial_migration_emits_expected_postgresql_schema() -> None:
    backend_directory = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "DATABASE_URL": "postgresql+asyncpg://talkbuddy_user@localhost:5432/talkbuddy_db",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=backend_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    for table_name in Base.metadata.tables:
        assert f"CREATE TABLE {table_name}" in result.stdout
    assert "CREATE UNIQUE INDEX ix_users_email" in result.stdout
    assert "CREATE UNIQUE INDEX ix_user_sessions_token_hash" in result.stdout
    assert "UNIQUE (user_id)" in result.stdout
    assert result.stdout.count("ON DELETE CASCADE") == 4
