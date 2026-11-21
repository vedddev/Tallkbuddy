"""Authentication API tests with a fresh, isolated database per test."""

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME, hash_session_token
from app.core.config import Settings
from app.db.base import Base
from app.db.models import User, UserSession
from app.db.session import get_db_session
from app.main import create_app


VALID_USER = {
    "name": "  Test User  ",
    "email": "Test.User@example.com",
    "password": "correct-horse-battery-staple",
}


class AuthHarness:
    def __init__(
        self, client: TestClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        self.client = client
        self.sessionmaker = sessionmaker

    def register(self) -> None:
        response = self.client.post("/api/auth/register", json=VALID_USER)
        assert response.status_code == 201, response.text

    def login(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
        )
        assert response.status_code == 200, response.text


@pytest.fixture
def auth_harness() -> Iterator[AuthHarness]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app(
        Settings(app_env="test", auth_login_rate_limit=20, auth_register_rate_limit=20)
    )

    async def isolated_session():
        async with maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db_session] = isolated_session
    with TestClient(application) as client:
        # Keep the SQLite connection on TestClient's portal loop for its full
        # lifetime. Cross-loop setup/disposal can strand aiosqlite close tasks
        # when the portal shuts down on Linux.
        client.portal.call(create_schema)
        yield AuthHarness(client, maker)
        client.portal.call(engine.dispose)

    application.dependency_overrides.clear()


def test_registration_persists_argon2id_hash_and_hides_it(auth_harness: AuthHarness) -> None:
    response = auth_harness.client.post("/api/auth/register", json=VALID_USER)

    assert response.status_code == 201
    assert response.json()["name"] == "Test User"
    assert response.json()["email"] == "test.user@example.com"
    assert "password_hash" not in response.json()
    assert "password" not in response.json()

    async def check_hash() -> None:
        async with auth_harness.sessionmaker() as db:
            user = await db.scalar(select(User).where(User.email == "test.user@example.com"))
            assert user is not None
            assert user.password_hash.startswith("$argon2id$")
            assert user.password_hash != VALID_USER["password"]

    asyncio.run(check_hash())


def test_duplicate_email_registration_returns_conflict(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    response = auth_harness.client.post("/api/auth/register", json=VALID_USER)
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "A", "email": "valid@example.com", "password": "long-enough-password"},
        {"name": "Valid", "email": "not-an-email", "password": "long-enough-password"},
        {"name": "Valid", "email": "valid@example.com", "password": "short"},
    ],
)
def test_invalid_registration_returns_422(auth_harness: AuthHarness, payload: dict[str, str]) -> None:
    response = auth_harness.client.post("/api/auth/register", json=payload)
    assert response.status_code == 422


def test_login_sets_opaque_cookie_and_stores_only_hash(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    response = auth_harness.client.post(
        "/api/auth/login",
        json={"email": "TEST.USER@example.com", "password": VALID_USER["password"]},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "test.user@example.com"
    assert "token" not in response.json()
    assert "password_hash" not in response.json()
    token = auth_harness.client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None and len(token) >= 40
    assert auth_harness.client.cookies.get(CSRF_COOKIE_NAME)

    async def check_session() -> None:
        async with auth_harness.sessionmaker() as db:
            saved = await db.scalar(select(UserSession))
            assert saved is not None
            assert saved.token_hash == hash_session_token(token)
            assert token not in saved.token_hash
            assert saved.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)

    asyncio.run(check_session())


@pytest.mark.parametrize(
    "email,password",
    [
        ("test.user@example.com", "incorrect-password"),
        ("missing@example.com", "incorrect-password"),
    ],
)
def test_incorrect_credentials_have_generic_response(
    auth_harness: AuthHarness, email: str, password: str
) -> None:
    auth_harness.register()
    response = auth_harness.client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_me_requires_authentication(auth_harness: AuthHarness) -> None:
    response = auth_harness.client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user_with_valid_session(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    auth_harness.login()
    response = auth_harness.client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "test.user@example.com"
    assert "password_hash" not in response.json()


def test_logout_revokes_session_and_clears_cookies(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    auth_harness.login()
    token = auth_harness.client.cookies.get(SESSION_COOKIE_NAME)
    csrf = auth_harness.client.cookies.get(CSRF_COOKIE_NAME)

    response = auth_harness.client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})
    assert response.status_code == 200
    assert auth_harness.client.cookies.get(SESSION_COOKIE_NAME) is None
    assert auth_harness.client.get("/api/auth/me").status_code == 401
    auth_harness.client.cookies.set(SESSION_COOKIE_NAME, token)
    assert auth_harness.client.get("/api/auth/me").status_code == 401

    async def check_revocation() -> None:
        async with auth_harness.sessionmaker() as db:
            saved = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_session_token(token)))
            assert saved is not None and saved.revoked_at is not None

    asyncio.run(check_revocation())


def test_expired_session_is_rejected(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    auth_harness.login()

    async def expire_session() -> None:
        async with auth_harness.sessionmaker() as db:
            saved = await db.scalar(select(UserSession))
            assert saved is not None
            saved.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

    asyncio.run(expire_session())
    assert auth_harness.client.get("/api/auth/me").status_code == 401


def test_development_cookie_attributes(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    response = auth_harness.client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    session_cookie = next(
        value for value in response.headers.get_list("set-cookie") if value.startswith(SESSION_COOKIE_NAME)
    )
    csrf_cookie = next(
        value for value in response.headers.get_list("set-cookie") if value.startswith(CSRF_COOKIE_NAME)
    )
    assert "httponly" in session_cookie.lower()
    assert "secure" not in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert Settings(app_env="production", auth_cookie_secure=False).cookie_secure is True


def test_production_cookie_is_secure_and_samesite_is_configurable(auth_harness: AuthHarness) -> None:
    auth_harness.client.app.state.settings = Settings(
        app_env="production", auth_cookie_secure=False, auth_cookie_samesite="strict"
    )
    auth_harness.register()
    response = auth_harness.client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    session_cookie = next(
        value for value in response.headers.get_list("set-cookie") if value.startswith(SESSION_COOKIE_NAME)
    )
    assert "secure" in session_cookie.lower()
    assert "httponly" in session_cookie.lower()
    assert "samesite=strict" in session_cookie.lower()


def test_login_rate_limit_returns_429(auth_harness: AuthHarness) -> None:
    limiter = auth_harness.client.app.state.auth_limiters["login"]
    limiter.limit = 2
    for _ in range(2):
        response = auth_harness.client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401
    response = auth_harness.client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1


def test_registration_rate_limit_returns_429(auth_harness: AuthHarness) -> None:
    limiter = auth_harness.client.app.state.auth_limiters["register"]
    limiter.limit = 1
    auth_harness.register()
    response = auth_harness.client.post(
        "/api/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "long-enough-password"},
    )
    assert response.status_code == 429


def test_csrf_and_origin_rejections(auth_harness: AuthHarness) -> None:
    auth_harness.register()
    auth_harness.login()

    assert auth_harness.client.post("/api/auth/logout").status_code == 403
    assert auth_harness.client.post(
        "/api/auth/logout", headers={CSRF_HEADER_NAME: "incorrect"}
    ).status_code == 403
    assert auth_harness.client.post(
        "/api/auth/logout",
        headers={CSRF_HEADER_NAME: auth_harness.client.cookies.get(CSRF_COOKIE_NAME), "Origin": "https://attacker.example"},
    ).status_code == 403
    assert auth_harness.client.get("/api/auth/me").status_code == 200


def test_cross_origin_login_and_non_json_body_are_rejected(auth_harness: AuthHarness) -> None:
    cross_origin = auth_harness.client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
        headers={"Origin": "https://attacker.example"},
    )
    form_body = auth_harness.client.post(
        "/api/auth/login",
        data={"email": "missing@example.com", "password": "wrong-password"},
    )
    assert cross_origin.status_code == 403
    assert form_body.status_code == 415


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5173"])
def test_registration_accepts_local_vite_origin_in_development(
    auth_harness: AuthHarness, origin: str
) -> None:
    settings = Settings(app_env="development", cors_origins=[], _env_file=None)
    auth_harness.client.app.state.settings = settings
    response = auth_harness.client.post(
        "/api/auth/register", json=VALID_USER, headers={"Origin": origin}
    )
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "test.user@example.com"

    with TestClient(create_app(settings)) as client:
        preflight = client.options(
            "/api/auth/register",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin


def test_local_vite_origin_is_not_implicitly_trusted_in_production(
    auth_harness: AuthHarness,
) -> None:
    auth_harness.client.app.state.settings = Settings(
        app_env="production", cors_origins=[], _env_file=None
    )
    response = auth_harness.client.post(
        "/api/auth/register", json=VALID_USER,
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Untrusted origin"}
