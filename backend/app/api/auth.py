"""Registration, login, logout, and current-user routes."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthenticatedSession, require_csrf, require_current_user
from app.auth.schemas import LoginRequest, MessageResponse, RegistrationRequest, UserResponse
from app.auth.security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, csrf_token_for_session
from app.auth.service import (
    DuplicateEmailError,
    authenticate_user,
    create_session,
    register_user,
    revoke_session,
)
from app.core.config import Settings
from app.db.models import User
from app.db.session import get_db_session


router = APIRouter(prefix="/auth", tags=["auth"])


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def require_trusted_origin(request: Request) -> None:
    """Reject browser writes that originate outside this API's allowed origins."""

    settings: Settings = request.app.state.settings
    allowed = {_origin(str(request.base_url)), *settings.allowed_origins}
    supplied = request.headers.get("origin") or request.headers.get("referer")
    if supplied and _origin(supplied) not in allowed:
        raise HTTPException(status_code=403, detail="Untrusted origin")


def require_json_body(request: Request) -> None:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")


def _check_rate_limit(request: Request, action: str) -> None:
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.auth_limiters[action]
    retry_after = limiter.retry_after(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )


def limit_registration(request: Request) -> None:
    _check_rate_limit(request, "register")


def limit_login(request: Request) -> None:
    _check_rate_limit(request, "login")


def _set_auth_cookies(response: Response, token: str, settings: Settings) -> None:
    cookie_options = {
        "max_age": settings.auth_session_days * 86400,
        "secure": settings.cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE_NAME, token, httponly=True, **cookie_options)
    response.set_cookie(CSRF_COOKIE_NAME, csrf_token_for_session(token), httponly=False, **cookie_options)
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin), Depends(require_json_body), Depends(limit_registration)],
)
async def register(
    payload: RegistrationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    try:
        return await register_user(db, payload)
    except DuplicateEmailError:
        raise HTTPException(status_code=409, detail="Email already registered") from None


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(require_trusted_origin), Depends(require_json_body), Depends(limit_login)],
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    user = await authenticate_user(db, str(payload.email), payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    settings: Settings = request.app.state.settings
    token = await create_session(db, user, settings.auth_session_days)
    _set_auth_cookies(response, token, settings)
    return user


@router.post(
    "/logout",
    response_model=MessageResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def logout(
    request: Request,
    response: Response,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    await revoke_session(db, authenticated.session)
    settings: Settings = request.app.state.settings
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=settings.cookie_secure, samesite=settings.auth_cookie_samesite
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, path="/", secure=settings.cookie_secure, samesite=settings.auth_cookie_samesite
    )
    response.headers["Cache-Control"] = "no-store"
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserResponse)
async def get_me(response: Response, user: User = Depends(require_current_user)) -> User:
    response.headers["Cache-Control"] = "no-store"
    return user
