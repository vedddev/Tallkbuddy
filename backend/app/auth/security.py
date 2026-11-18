"""Password, session-token, and CSRF primitives."""

import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from starlette.concurrency import run_in_threadpool


SESSION_COOKIE_NAME = "talkbuddy_session"
CSRF_COOKIE_NAME = "talkbuddy_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)
_dummy_password_hash = password_hasher.hash("not-a-real-user-password")
_password_slots = asyncio.Semaphore(4)


async def hash_password(password: str) -> str:
    async with _password_slots:
        return await run_in_threadpool(password_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Spend comparable verification work for absent users."""

    try:
        async with _password_slots:
            return await run_in_threadpool(
                password_hasher.verify, password_hash or _dummy_password_hash, password
            )
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session(token: str) -> str:
    """Bind the readable CSRF cookie to the secret session token."""

    return hmac.new(token.encode("utf-8"), b"talkbuddy-csrf-v1", hashlib.sha256).hexdigest()


def valid_csrf_token(token: str, submitted: str) -> bool:
    return hmac.compare_digest(csrf_token_for_session(token), submitted)
