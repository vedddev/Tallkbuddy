"""Owned translation session creation and updates."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_trusted_origin
from app.auth.dependencies import AuthenticatedSession, require_csrf
from app.db.session import get_db_session
from app.history.schemas import (
    CreateTranslationSession,
    TranslationSessionResponse,
    UpdateSessionTitle,
)
from app.history.service import (
    create_translation_session,
    end_translation_session,
    update_session_title,
)


router = APIRouter(
    prefix="/translation-sessions",
    tags=["translation-sessions"],
    dependencies=[Depends(require_trusted_origin)],
)


@router.post("", response_model=TranslationSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateTranslationSession,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> TranslationSessionResponse:
    record = await create_translation_session(db, authenticated.user.id, payload)
    return TranslationSessionResponse.model_validate(record)


@router.patch("/{session_id}", response_model=TranslationSessionResponse)
async def patch_session_title(
    session_id: UUID,
    payload: UpdateSessionTitle,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> TranslationSessionResponse:
    record = await update_session_title(db, authenticated.user.id, session_id, payload.title)
    return TranslationSessionResponse.model_validate(record)


@router.post("/{session_id}/end", response_model=TranslationSessionResponse)
async def end_session(
    session_id: UUID,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> TranslationSessionResponse:
    record = await end_translation_session(db, authenticated.user.id, session_id)
    return TranslationSessionResponse.model_validate(record)
