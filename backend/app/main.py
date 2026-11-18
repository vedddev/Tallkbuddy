"""FastAPI application entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.ai.service import AIServiceError
from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.preferences import router as preferences_router
from app.api.translation_sessions import router as translation_sessions_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.session import DatabaseConfigurationError, get_engine
from app.history.service import HistoryError
from app.ws.limits import ConnectionRegistry
from app.ws.translate import router as websocket_router


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    """Release pooled database connections during application shutdown."""

    try:
        yield
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the HTTP application."""

    settings = settings or get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.state.settings = settings
    application.state.auth_limiters = {
        "login": SlidingWindowRateLimiter(settings.auth_login_rate_limit, settings.auth_rate_window_seconds),
        "register": SlidingWindowRateLimiter(settings.auth_register_rate_limit, settings.auth_rate_window_seconds),
    }
    application.state.websocket_connections = ConnectionRegistry(settings.ws_max_connections_per_user)
    application.state.ai_provider_slots = asyncio.Semaphore(settings.ai_max_concurrent_provider_calls)

    @application.exception_handler(DatabaseConfigurationError)
    async def database_configuration_error_handler(
        _request: Request, _exc: DatabaseConfigurationError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @application.exception_handler(AIServiceError)
    async def ai_service_error_handler(_request: Request, exc: AIServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.public_detail})

    @application.exception_handler(HistoryError)
    async def history_error_handler(_request: Request, exc: HistoryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.public_detail})

    @application.exception_handler(SQLAlchemyError)
    async def database_operation_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logging.getLogger(__name__).warning("Database operation failed (%s)", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api")
    application.include_router(auth_router, prefix="/api")
    application.include_router(ai_router, prefix="/api")
    application.include_router(preferences_router, prefix="/api")
    application.include_router(translation_sessions_router, prefix="/api")
    application.include_router(history_router, prefix="/api")
    application.include_router(websocket_router)

    logging.getLogger(__name__).info(
        "TalkBuddy API initialized (%s); Groq translation model=%s",
        settings.app_env,
        settings.groq_translation_model,
    )
    return application


app = create_app()
