"""Paginated owned translation history and deletion."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_trusted_origin
from app.auth.dependencies import AuthenticatedSession, require_csrf, require_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.history.schemas import ClearHistoryResponse, SessionDetail, SessionPage
from app.history.service import clear_history, delete_session, get_session_detail, list_sessions


router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=SessionPage)
async def read_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    order: Literal["newest", "oldest"] = "newest",
    user: User = Depends(require_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SessionPage:
    return await list_sessions(db, user.id, limit, offset, order)


@router.get("/{session_id}", response_model=SessionDetail)
async def read_session_history(
    session_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    order: Literal["newest", "oldest"] = "oldest",
    user: User = Depends(require_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SessionDetail:
    return await get_session_detail(db, user.id, session_id, limit, offset, order)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
async def remove_session_history(
    session_id: UUID,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    await delete_session(db, authenticated.user.id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", response_model=ClearHistoryResponse, dependencies=[Depends(require_trusted_origin)])
async def remove_all_history(
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> ClearHistoryResponse:
    deleted = await clear_history(db, authenticated.user.id)
    return ClearHistoryResponse(deleted_sessions=deleted)
