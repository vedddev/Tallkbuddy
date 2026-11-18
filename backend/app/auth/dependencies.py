"""Reusable authentication and CSRF dependencies."""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import CSRF_HEADER_NAME, SESSION_COOKIE_NAME, valid_csrf_token
from app.auth.service import find_active_session
from app.db.models import User, UserSession
from app.db.session import get_db_session


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: UserSession
    token: str


async def require_authenticated_session(
    request: Request, db: AsyncSession = Depends(get_db_session)
) -> AuthenticatedSession:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    active = await find_active_session(db, token)
    if active is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    session, user = active
    return AuthenticatedSession(user=user, session=session, token=token)


async def require_current_user(
    authenticated: AuthenticatedSession = Depends(require_authenticated_session),
) -> User:
    """Use this dependency for future protected read endpoints."""

    return authenticated.user


async def require_csrf(
    authenticated: AuthenticatedSession = Depends(require_authenticated_session),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER_NAME),
) -> AuthenticatedSession:
    """Use this dependency for all future cookie-authenticated writes."""

    if not csrf_header or not valid_csrf_token(authenticated.token, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return authenticated
