"""Opt-in local development HTTP/WebSocket and live text-provider smoke test.

Creates and removes only its own random local test account. It never captures audio.
Run with --live to make the two explicitly requested billable Groq text calls.
"""

import argparse
import asyncio
import secrets
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from app.core.config import Settings
from app.db.models import User


ORIGIN = "http://127.0.0.1:5173"


def make_test_email() -> str:
    """Use an email-validator-accepted reserved example domain."""

    return f"local-verify-{uuid4().hex}@example.com"


def _check(label: str, passed: bool) -> None:
    print(f"{'PASS' if passed else 'FAIL'} {label}")
    if not passed:
        raise RuntimeError(label)


async def _remove_test_user(database_url: str, user_id: UUID, email: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(delete(User).where(User.id == user_id, User.email == email))
            return result.rowcount == 1
    finally:
        await engine.dispose()


def main(live: bool = False) -> int:
    settings = Settings()
    try:
        database = make_url(settings.database_url or "")
    except Exception:
        print("REFUSED: local verification requires a valid local PostgreSQL URL.")
        return 2
    if settings.app_env != "development" or database.drivername != "postgresql+asyncpg" or database.host not in {"localhost", "127.0.0.1"}:
        print("REFUSED: local verification requires development mode and a local PostgreSQL URL.")
        return 2
    if live and not settings.groq_api_key:
        print("REFUSED: live Groq calls require a configured key.")
        return 2

    email = make_test_email()
    password = secrets.token_urlsafe(24)
    user_id: UUID | None = None
    result_code = 1
    client = httpx.Client(base_url=ORIGIN, timeout=65)
    try:
        _check("Vite proxy liveness", client.get("/api/health").status_code == 200)
        _check("Vite proxy database readiness", client.get("/api/health/ready").status_code == 200)
        _check("unauthenticated API", client.get("/api/auth/me").status_code == 401)
        registration = client.post("/api/auth/register", json={"name": "Local Verification", "email": email, "password": password}, headers={"Origin": ORIGIN})
        _check(f"registration HTTP {registration.status_code}", registration.status_code == 201)
        user_id = UUID(registration.json()["id"])
        login = client.post("/api/auth/login", json={"email": email, "password": password}, headers={"Origin": ORIGIN})
        _check("login", login.status_code == 200)
        session = client.cookies.get("talkbuddy_session")
        csrf = client.cookies.get("talkbuddy_csrf")
        cookie_headers = login.headers.get_list("set-cookie")
        session_header = next((item.lower() for item in cookie_headers if item.startswith("talkbuddy_session=")), "")
        csrf_header = next((item.lower() for item in cookie_headers if item.startswith("talkbuddy_csrf=")), "")
        _check("development session and CSRF cookies", bool(session and csrf) and
               "httponly" in session_header and "httponly" not in csrf_header and
               "samesite=lax" in session_header and ("secure" in session_header) == settings.cookie_secure)
        _check("authenticated API", client.get("/api/auth/me").status_code == 200)
        _check("CSRF rejection", client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 403)

        ws_url = "ws://127.0.0.1:5173/ws/translate"
        cookie_header = {"Cookie": f"talkbuddy_session={session}"}
        with connect(ws_url, origin=ORIGIN, additional_headers=cookie_header, open_timeout=10, close_timeout=5) as socket:
            socket.send('{"type":"start","target_language":"hi","audio_format":"wav"}')
            _check("authenticated WebSocket through Vite", '"type":"ready"' in socket.recv(timeout=10).replace(" ", ""))
            socket.send('{"type":"stop"}')
        try:
            with connect(ws_url, origin="http://untrusted.invalid", additional_headers=cookie_header,
                         open_timeout=10, close_timeout=5):
                rejected = False
        except InvalidStatus as exc:
            rejected = exc.response.status_code == 403
        _check("WebSocket Origin rejection", rejected)

        if live:
            for language, phrase in (
                ("hi", "Hello everyone, welcome to our meeting."),
                ("mr", "Today we are testing our real-time translation application."),
            ):
                response = client.post("/api/ai/translate", json={"text": phrase, "target_language": language},
                                       headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
                _check(f"live Groq text translation {language} HTTP", response.status_code == 200)
                payload = response.json()
                translated = payload.get("translated_text", "")
                _check(f"live Groq text translation {language} response", payload.get("target_language") == language and
                       isinstance(translated, str) and bool(translated.strip()))
                print(f"OBSERVED {language} Devanagari characters={any(chr(code) in translated for code in range(0x900, 0x980))}")

        logout = client.post("/api/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
        _check("logout", logout.status_code == 200)
        _check("revoked session", client.get("/api/auth/me", headers=cookie_header).status_code == 401)
        result_code = 0
    except Exception as exc:
        print(f"FAIL local smoke stage={str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}")
    finally:
        client.close()
        if user_id is not None:
            try:
                removed = asyncio.run(_remove_test_user(settings.database_url, user_id, email))
                print(f"{'PASS' if removed else 'FAIL'} local test-account cleanup")
                if not removed:
                    result_code = 1
            except Exception:
                print("FAIL local test-account cleanup; inspect development database privately.")
                result_code = 1
    return result_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make two billable Groq text-translation requests")
    args = parser.parse_args()
    raise SystemExit(main(live=args.live))
