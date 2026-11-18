"""Health-check route."""

from typing import Literal

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session


router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report that the application is running."""

    return HealthResponse(status="ok")


@router.get("/health/db", response_model=HealthResponse)
async def get_database_health(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    """Check database connectivity without exposing connection details."""

    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Database health check failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    return HealthResponse(status="ok")
