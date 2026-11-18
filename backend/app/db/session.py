"""Async SQLAlchemy engine and request-scoped sessions."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


class DatabaseConfigurationError(RuntimeError):
    """Database URL is missing or incompatible with the async driver."""


@lru_cache
def get_engine() -> AsyncEngine:
    """Create the connection pool without opening a connection."""

    settings = get_settings()
    url = settings.database_url
    if not url:
        raise DatabaseConfigurationError("DATABASE_URL must use the postgresql+asyncpg driver")
    try:
        parsed_url = make_url(url)
    except (ArgumentError, ValueError):
        raise DatabaseConfigurationError("DATABASE_URL is invalid") from None
    if parsed_url.drivername != "postgresql+asyncpg":
        raise DatabaseConfigurationError("DATABASE_URL must use the postgresql+asyncpg driver")
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        connect_args={"command_timeout": settings.database_command_timeout_seconds},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Provide sessions that never expire ORM objects after commit."""

    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a session, rolling back on request failure and closing on exit."""

    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
