"""Current user's language and history-saving preferences."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_trusted_origin
from app.auth.dependencies import AuthenticatedSession, require_csrf, require_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.history.schemas import PreferenceResponse, PreferenceUpdate
from app.history.service import get_preferences, update_preferences


router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferenceResponse)
async def read_preferences(
    user: User = Depends(require_current_user), db: AsyncSession = Depends(get_db_session)
) -> PreferenceResponse:
    return await get_preferences(db, user.id)


@router.patch(
    "",
    response_model=PreferenceResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def patch_preferences(
    payload: PreferenceUpdate,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> PreferenceResponse:
    return await update_preferences(db, authenticated.user.id, payload)
