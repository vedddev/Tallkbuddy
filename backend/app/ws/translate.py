"""Sequential, authenticated translation of complete WAV messages."""

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.service import (
    AIInputError,
    AINoSpeechError,
    AIProviderFailure,
    AIProviderTimeout,
    AIProviderUnavailable,
    AIService,
    ai_service_context,
)
from app.auth.security import SESSION_COOKIE_NAME
from app.auth.service import find_active_session
from app.core.config import Settings
from app.db.session import get_db_session
from app.history.service import (
    HistoryConflict,
    HistoryDisabled,
    HistoryNotFound,
    HistorySessionEnded,
    fingerprint_audio,
    get_saved_message,
    require_saving_allowed,
    save_translation,
)
from app.ws.audio import InvalidAudioChunk, validate_wav_chunk
from app.ws.limits import ConnectionRegistry
from app.ws.protocol import (
    ChunkMessage,
    ErrorMessage,
    ProcessingMessage,
    ReadyMessage,
    ResultMessage,
    StartMessage,
    StopMessage,
)


router = APIRouter()
logger = logging.getLogger(__name__)


async def _send(websocket: WebSocket, message: BaseModel) -> bool:
    try:
        payload = message.model_dump(mode="json")
        if isinstance(message, ResultMessage) and message.saved is None:
            payload.pop("saved")
            payload.pop("message_id")
        if isinstance(message, ResultMessage):
            if message.transcription_time_ms is None:
                payload.pop("transcription_time_ms")
            if message.translation_time_ms is None:
                payload.pop("translation_time_ms")
        await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, OSError, RuntimeError):
        return False


async def _error(
    websocket: WebSocket, code: str, message: str, recoverable: bool
) -> bool:
    return await _send(
        websocket, ErrorMessage(code=code, message=message, recoverable=recoverable)
    )


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except (WebSocketDisconnect, OSError, RuntimeError):
        pass


async def _active_user_id(db: AsyncSession, token: str) -> UUID | None:
    """Check the live database session and end the read transaction."""

    try:
        active = await find_active_session(db, token)
        return active[1].id if active is not None else None
    finally:
        await db.rollback()


def _origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False
    own_scheme = "https" if websocket.url.scheme == "wss" else "http"
    own_origin = f"{own_scheme}://{host}"
    return origin == own_origin or origin in settings.allowed_origins


def _parse_start(payload: dict[str, object]) -> tuple[StartMessage | None, str]:
    if payload.get("audio_format") not in {None, "wav"}:
        return None, "unsupported_audio_format"
    try:
        return StartMessage.model_validate(payload), ""
    except ValidationError as exc:
        if any(
            error["loc"]
            and error["loc"][0] in {"target_language", "source_language"}
            and error["type"] != "missing"
            for error in exc.errors()
        ):
            return None, "unsupported_language"
        return None, "invalid_start"


async def _history_error(websocket: WebSocket, exc: Exception) -> bool:
    if isinstance(exc, HistoryDisabled):
        return await _error(websocket, "history_disabled", "History saving is disabled", True)
    if isinstance(exc, HistoryNotFound):
        return await _error(websocket, "history_session_invalid", "History session not found", True)
    if isinstance(exc, HistorySessionEnded):
        return await _error(websocket, "history_session_ended", "History session has ended", True)
    if isinstance(exc, HistoryConflict):
        return await _error(websocket, "idempotency_conflict", "History request conflicts", True)
    logger.warning("WebSocket history operation failed (%s)", type(exc).__name__)
    return await _error(websocket, "storage_unavailable", "History storage unavailable", True)


async def _process_chunk(
    websocket: WebSocket,
    db: AsyncSession,
    token: str,
    user_id: UUID,
    service: AIService,
    start: StartMessage,
    audio: bytes,
    chunk_id: int,
    settings: Settings,
    request_id: UUID | None,
) -> bool:
    began = perf_counter()
    transcription_time_ms: int | None = None
    translation_time_ms: int | None = None
    fingerprint = fingerprint_audio(audio, start.target_language) if start.save_history else None
    if start.save_history:
        try:
            assert start.session_id is not None and request_id is not None and fingerprint is not None
            existing = await get_saved_message(
                db, user_id, start.session_id, start.target_language, request_id, fingerprint
            )
            cached = (
                (
                    existing.id,
                    existing.original_text,
                    existing.translated_text,
                    existing.detected_language,
                )
                if existing is not None
                else None
            )
            await db.rollback()
        except (HistoryDisabled, HistoryNotFound, HistorySessionEnded, HistoryConflict, SQLAlchemyError) as exc:
            await db.rollback()
            return await _history_error(websocket, exc)
        if cached is not None:
            try:
                active_user_id = await _active_user_id(db, token)
            except SQLAlchemyError as exc:
                logger.warning("WebSocket session check failed (%s)", type(exc).__name__)
                await _error(websocket, "session_check_failed", "Session check failed", False)
                await _close(websocket, 1011)
                return False
            if active_user_id != user_id:
                await _error(websocket, "session_invalid", "Session is no longer valid", False)
                await _close(websocket, 1008)
                return False
            message_id, original, translated, detected = cached
            return await _send(
                websocket,
                ResultMessage(
                    chunk_id=chunk_id,
                    original=original,
                    translated=translated,
                    detected_language=detected,
                    target_language=start.target_language,
                    processing_time_ms=max(0, int((perf_counter() - began) * 1000)),
                    saved=True,
                    message_id=message_id,
                ),
            )

    try:
        async with asyncio.timeout(settings.ws_processing_timeout_seconds):
            transcription_began = perf_counter()
            if start.source_language:
                transcription = await service.transcribe(audio, "audio.wav", start.source_language)
            else:
                transcription = await service.transcribe(audio, "audio.wav")
            transcription_time_ms = max(0, int((perf_counter() - transcription_began) * 1000))
            if await _active_user_id(db, token) != user_id:
                await _error(websocket, "session_invalid", "Session is no longer valid", False)
                await _close(websocket, 1008)
                return False
            translation_began = perf_counter()
            translation = await service.translate(transcription.text, start.target_language)
            translation_time_ms = max(0, int((perf_counter() - translation_began) * 1000))
            if await _active_user_id(db, token) != user_id:
                await _error(websocket, "session_invalid", "Session is no longer valid", False)
                await _close(websocket, 1008)
                return False
            if start.save_history:
                assert start.session_id is not None and request_id is not None and fingerprint is not None
                saved = await save_translation(
                    db, user_id, start.session_id, start.target_language, request_id, fingerprint,
                    transcription.text, translation.translated_text, transcription.detected_language,
                )
                original = saved.original_text
                translated = saved.translated_text
                detected = saved.detected_language
                message_id = saved.id
            else:
                original = transcription.text
                translated = translation.translated_text
                detected = transcription.detected_language
                message_id = None
    except AINoSpeechError:
        return await _error(websocket, "no_speech", "No speech detected", True)
    except AIProviderTimeout:
        return await _error(websocket, "provider_timeout", "AI provider timed out", True)
    except AIProviderUnavailable:
        return await _error(websocket, "provider_unavailable", "AI provider unavailable", True)
    except AIProviderFailure:
        return await _error(websocket, "provider_error", "AI processing failed", True)
    except AIInputError:
        return await _error(websocket, "invalid_input", "Audio could not be processed", True)
    except TimeoutError:
        return await _error(websocket, "processing_timeout", "Processing timed out", True)
    except (HistoryDisabled, HistoryNotFound, HistorySessionEnded, HistoryConflict, SQLAlchemyError) as exc:
        await db.rollback()
        return await _history_error(websocket, exc)
    except Exception as exc:
        logger.warning("WebSocket chunk processing failed (%s)", type(exc).__name__)
        await _error(websocket, "internal_error", "Processing failed", False)
        await _close(websocket, 1011)
        return False

    elapsed_ms = max(0, int((perf_counter() - began) * 1000))
    return await _send(
        websocket,
        ResultMessage(
            chunk_id=chunk_id,
            original=original,
            translated=translated,
            detected_language=detected,
            target_language=start.target_language,
            processing_time_ms=elapsed_ms,
            transcription_time_ms=transcription_time_ms,
            translation_time_ms=translation_time_ms,
            saved=True if start.save_history else None,
            message_id=message_id,
        ),
    )


@router.websocket("/ws/translate")
async def translate_websocket(
    websocket: WebSocket, db: AsyncSession = Depends(get_db_session)
) -> None:
    settings: Settings = websocket.app.state.settings
    if not _origin_allowed(websocket, settings):
        await _close(websocket, 1008)
        return

    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        await _close(websocket, 1008)
        return
    try:
        user_id = await _active_user_id(db, token)
    except Exception as exc:
        logger.warning("WebSocket authentication lookup failed (%s)", type(exc).__name__)
        await _close(websocket, 1011)
        return
    if user_id is None:
        await _close(websocket, 1008)
        return

    registry: ConnectionRegistry = websocket.app.state.websocket_connections
    if not await registry.acquire(user_id):
        await _close(websocket, 1013)
        return

    try:
        await websocket.accept()
        start: StartMessage | None = None
        service: AIService | None = None
        chunk_id = 0
        pending_request_id: UUID | None = None
        async with AsyncExitStack() as stack:
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), timeout=settings.ws_idle_timeout_seconds
                    )
                except TimeoutError:
                    await _error(websocket, "idle_timeout", "Connection was idle", False)
                    await _close(websocket, 1000)
                    return
                except WebSocketDisconnect:
                    return

                if message["type"] == "websocket.disconnect":
                    return
                try:
                    active_user_id = await _active_user_id(db, token)
                except Exception as exc:
                    logger.warning("WebSocket session check failed (%s)", type(exc).__name__)
                    await _error(websocket, "session_check_failed", "Session check failed", False)
                    await _close(websocket, 1011)
                    return
                if active_user_id != user_id:
                    await _error(websocket, "session_invalid", "Session is no longer valid", False)
                    await _close(websocket, 1008)
                    return

                text = message.get("text")
                if text is not None:
                    if len(text.encode("utf-8")) > settings.ws_max_control_bytes:
                        if not await _error(websocket, "invalid_message", "Control message too large", True):
                            return
                        continue
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = None
                    if not isinstance(payload, dict):
                        if not await _error(websocket, "invalid_message", "Invalid control message", True):
                            return
                        continue

                    if payload.get("type") == "stop":
                        try:
                            StopMessage.model_validate(payload)
                        except ValidationError:
                            if not await _error(websocket, "invalid_message", "Invalid stop message", True):
                                return
                            continue
                        await _close(websocket, 1000)
                        return
                    if payload.get("type") == "start":
                        if start is not None:
                            if not await _error(websocket, "invalid_state", "Already started", True):
                                return
                            continue
                        parsed, error_code = _parse_start(payload)
                        if parsed is None:
                            if not await _error(websocket, error_code, "Invalid start message", True):
                                return
                            continue
                        if parsed.save_history and parsed.session_id is None:
                            if not await _error(websocket, "invalid_start", "session_id is required to save", True):
                                return
                            continue
                        if not parsed.save_history and parsed.session_id is not None:
                            if not await _error(websocket, "invalid_start", "session_id requires saving", True):
                                return
                            continue
                        if parsed.save_history:
                            try:
                                await require_saving_allowed(
                                    db, user_id, parsed.session_id, parsed.target_language
                                )
                                await db.rollback()
                            except (HistoryDisabled, HistoryNotFound, HistorySessionEnded, HistoryConflict, SQLAlchemyError) as exc:
                                await db.rollback()
                                if not await _history_error(websocket, exc):
                                    return
                                continue
                        try:
                            service = await stack.enter_async_context(
                                ai_service_context(settings, websocket.app.state.ai_provider_slots)
                            )
                        except AIProviderUnavailable:
                            await _error(websocket, "provider_unavailable", "AI provider unavailable", False)
                            await _close(websocket, 1011)
                            return
                        start = parsed
                        if not await _send(
                            websocket,
                            ReadyMessage(
                                target_language=start.target_language,
                                source_language=start.source_language,
                            ),
                        ):
                            return
                        continue

                    if payload.get("type") == "chunk":
                        if start is None or not start.save_history or pending_request_id is not None:
                            if not await _error(websocket, "invalid_state", "Chunk metadata is not expected", True):
                                return
                            continue
                        try:
                            chunk_meta = ChunkMessage.model_validate(payload)
                        except ValidationError:
                            if not await _error(websocket, "invalid_message", "Invalid chunk metadata", True):
                                return
                            continue
                        pending_request_id = chunk_meta.request_id
                        continue

                    if not await _error(websocket, "invalid_message", "Unknown control message", True):
                        return
                    continue

                audio = message.get("bytes")
                if not isinstance(audio, bytes):
                    if not await _error(websocket, "invalid_message", "Invalid message", True):
                        return
                    continue
                if start is None or service is None:
                    if not await _error(websocket, "invalid_state", "Send start before audio", True):
                        return
                    continue
                if start.save_history and pending_request_id is None:
                    if not await _error(websocket, "missing_request_id", "Send chunk metadata before audio", True):
                        return
                    continue
                if chunk_id >= settings.ws_max_chunks:
                    await _error(websocket, "chunk_limit", "Chunk limit reached", False)
                    await _close(websocket, 1000)
                    return
                if len(audio) > settings.ws_max_audio_bytes:
                    if not await _error(websocket, "audio_too_large", "Audio chunk too large", True):
                        return
                    continue
                try:
                    validate_wav_chunk(audio, settings.ws_max_audio_bytes)
                except InvalidAudioChunk:
                    if not await _error(websocket, "invalid_audio", "Invalid or incomplete WAV chunk", True):
                        return
                    continue

                chunk_id += 1
                request_id = pending_request_id
                pending_request_id = None
                if not await _send(websocket, ProcessingMessage(chunk_id=chunk_id)):
                    return
                if not await _process_chunk(
                    websocket, db, token, user_id, service, start, audio, chunk_id, settings, request_id
                ):
                    return
    except (WebSocketDisconnect, OSError, RuntimeError):
        return
    finally:
        await registry.release(user_id)
