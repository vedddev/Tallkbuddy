"""Database operations for registration and server-side sessions."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import RegistrationRequest
from app.auth.security import hash_password, hash_session_token, new_session_token, verify_password
from app.db.models import User, UserSession


class DuplicateEmailError(Exception):
    """The requested email is already registered."""


async def register_user(db: AsyncSession, payload: RegistrationRequest) -> User:
    user = User(
        name=payload.name,
        email=str(payload.email),
        password_hash=await hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DuplicateEmailError from None
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await db.scalar(select(User).where(User.email == email))
    valid_password = await verify_password(user.password_hash if user else None, password)
    if not user or not valid_password or not user.is_active:
        return None
    return user


async def create_session(db: AsyncSession, user: User, days: int) -> str:
    token = new_session_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(session)
    await db.commit()
    return token


async def find_active_session(db: AsyncSession, token: str) -> tuple[UserSession, User] | None:
    now = datetime.now(timezone.utc)
    statement = (
        select(UserSession, User)
        .join(User, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    return (await db.execute(statement)).one_or_none()


async def revoke_session(db: AsyncSession, session: UserSession) -> None:
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
