"""Sequential, authenticated translation of complete WAV messages."""

import asyncio
import base64
import json
import logging
from contextlib import AsyncExitStack
from time import perf_counter
from uuid import UUID, uuid4

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
from app.ai.languages import normalize_detected_language
from app.ai.tts import TTSError, synthesize_wav, tts_configured
from app.auth.security import SESSION_COOKIE_NAME
from app.auth.service import find_active_session
from app.core.config import Settings
from app.core.observability import chunk_id_context, websocket_id_context
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
from app.ws.audio import InvalidAudioChunk, validate_interim_wav, validate_wav_chunk
from app.ws.limits import ConnectionRegistry
from app.ws.protocol import (
    ChunkMessage,
    ErrorMessage,
    InterimAudioMessage,
    InterimCancelMessage,
    InterimCaptionMessage,
    InterimErrorMessage,
    ProcessingMessage,
    ReadyMessage,
    ResultMessage,
    SpeechAudioMessage,
    SpeechErrorMessage,
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
            if message.language_detection_source is None:
                payload.pop("language_detection_source")
            if message.transcription_time_ms is None:
                payload.pop("transcription_time_ms")
            if message.translation_time_ms is None:
                payload.pop("translation_time_ms")
        if isinstance(message, ErrorMessage):
            for field in ("chunk_id", "original", "detected_language", "language_detection_source"):
                if payload[field] is None:
                    payload.pop(field)
        if isinstance(message, ReadyMessage) and message.interim_captions is None:
            payload.pop("interim_captions")
        await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, OSError, RuntimeError):
        return False


async def _error(
    websocket: WebSocket, code: str, message: str, recoverable: bool,
    *, chunk_id: int | None = None, original: str | None = None,
    detected_language: str | None = None,
) -> bool:
    metrics = getattr(websocket.app.state, "metrics", None)
    if metrics is not None:
        metrics.increment("ws_errors")
        if code in {"provider_timeout", "processing_timeout"}:
            metrics.increment("provider_timeouts")
        elif code in {"provider_unavailable", "provider_error"}:
            metrics.increment("provider_errors")
    return await _send(
        websocket, ErrorMessage(
            code=code, message=message, recoverable=recoverable,
            chunk_id=chunk_id, original=original, detected_language=detected_language,
            language_detection_source=("stt" if detected_language else "unknown") if original else None,
        )
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


async def _cancel_interim(task: asyncio.Task[None] | None) -> None:
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # The child is expected to be cancelled; cancellation of this
            # WebSocket handler itself must still reach its caller.
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise


async def _process_interim(
    websocket: WebSocket, db: AsyncSession, auth_lock: asyncio.Lock,
    token: str, user_id: UUID, service: AIService, start: StartMessage,
    meta: InterimAudioMessage, audio: bytes, settings: Settings,
) -> None:
    try:
        async with asyncio.timeout(settings.ws_interim_timeout_seconds):
            if start.source_language:
                transcription = await service.transcribe(audio, "interim.wav", start.source_language)
            else:
                transcription = await service.transcribe(audio, "interim.wav")
        # The request-scoped DB session must never be used concurrently by two tasks.
        async with auth_lock:
            active = await _active_user_id(db, token) == user_id
        if not active:
            return
        await _send(websocket, InterimCaptionMessage(
            phrase_id=meta.phrase_id, revision=meta.revision,
            text=transcription.text, detected_language=normalize_detected_language(transcription.detected_language),
        ))
    except asyncio.CancelledError:
        raise
    except (TimeoutError, AIProviderTimeout):
        await _send(websocket, InterimErrorMessage(
            phrase_id=meta.phrase_id, revision=meta.revision,
            code="provider_timeout", message="Interim transcription timed out; final captions continue",
        ))
    except (AIProviderUnavailable, AIProviderFailure):
        await _send(websocket, InterimErrorMessage(
            phrase_id=meta.phrase_id, revision=meta.revision,
            code="provider_unavailable", message="Interim transcription unavailable; final captions continue",
        ))
    except (AINoSpeechError, AIInputError):
        await _send(websocket, InterimErrorMessage(
            phrase_id=meta.phrase_id, revision=meta.revision,
            code="no_speech", message="No clear interim speech; final captions continue",
        ))
    except SQLAlchemyError as exc:
        logger.warning("Interim session check failed (%s)", type(exc).__name__)
    except Exception as exc:
        logger.warning("Interim transcription failed (%s)", type(exc).__name__)
        await _send(websocket, InterimErrorMessage(
            phrase_id=meta.phrase_id, revision=meta.revision,
            code="provider_error", message="Interim transcription unavailable; final captions continue",
        ))


def _origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False
    own_scheme = "https" if websocket.url.scheme == "wss" else "http"
    own_origin = settings.public_origin if settings.app_env == "production" else f"{own_scheme}://{host}"
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


async def _send_result_and_speech(
    websocket: WebSocket, result: ResultMessage, start: StartMessage,
    db: AsyncSession, token: str, user_id: UUID, settings: Settings,
) -> bool:
    result_send_began = perf_counter()
    if not await _send(websocket, result):
        return False
    logger.debug(
        "WebSocket result sent chunk_id=%d processing_ms=%d stt_ms=%s translation_ms=%s send_ms=%d",
        result.chunk_id, result.processing_time_ms, result.transcription_time_ms,
        result.translation_time_ms, max(0, int((perf_counter() - result_send_began) * 1000)),
    )
    if not start.synthesize_speech:
        return True
    began = perf_counter()
    metrics = websocket.app.state.metrics
    try:
        async with asyncio.timeout(settings.tts_timeout_seconds + 2):
            async with websocket.app.state.ai_provider_slots:
                audio = await synthesize_wav(result.translated, result.target_language, settings)
        if await _active_user_id(db, token) != user_id:
            await _error(websocket, "session_invalid", "Session is no longer valid", False)
            await _close(websocket, 1008)
            return False
    except (TTSError, TimeoutError) as exc:
        metrics.increment("provider_errors")
        logger.warning("WebSocket speech synthesis unavailable (%s)", type(exc).__name__)
        return await _send(websocket, SpeechErrorMessage(
            chunk_id=result.chunk_id, code="speech_unavailable", message="Translated speech is unavailable",
        ))
    except SQLAlchemyError as exc:
        logger.warning("WebSocket session check failed (%s)", type(exc).__name__)
        await _error(websocket, "session_check_failed", "Session check failed", False)
        await _close(websocket, 1011)
        return False
    except Exception as exc:
        metrics.increment("provider_errors")
        logger.warning("WebSocket speech synthesis failed (%s)", type(exc).__name__)
        return await _send(websocket, SpeechErrorMessage(
            chunk_id=result.chunk_id, code="speech_unavailable", message="Translated speech is unavailable",
        ))
    finally:
        metrics.observe("tts", (perf_counter() - began) * 1000)
    speech_send_began = perf_counter()
    sent = await _send(websocket, SpeechAudioMessage(
        chunk_id=result.chunk_id, audio_base64=base64.b64encode(audio).decode("ascii"),
        preparation_time_ms=max(0, int((perf_counter() - began) * 1000)),
    ))
    if sent:
        logger.debug(
            "WebSocket speech audio sent chunk_id=%d tts_ms=%d send_ms=%d",
            result.chunk_id, max(0, int((speech_send_began - began) * 1000)),
            max(0, int((perf_counter() - speech_send_began) * 1000)),
        )
    return sent


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
            detected = normalize_detected_language(detected)
            return await _send_result_and_speech(
                websocket,
                ResultMessage(
                    chunk_id=chunk_id,
                    original=original,
                    translated=translated,
                    detected_language=detected,
                    language_detection_source="stt" if detected else "unknown",
                    target_language=start.target_language,
                    processing_time_ms=max(0, int((perf_counter() - began) * 1000)),
                    saved=True,
                    message_id=message_id,
                ),
                start, db, token, user_id, settings,
            )

    transcription = None
    detected_source = None
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
            detected_source = normalize_detected_language(transcription.detected_language)
            source_for_translation = start.source_language or detected_source
            translation_began = perf_counter()
            if detected_source == start.target_language and source_for_translation == start.target_language:
                translated_text = transcription.text
                translation_time_ms = 0
            else:
                translation = await service.translate(
                    transcription.text, start.target_language, source_language=source_for_translation
                )
                translated_text = translation.translated_text
                translation_time_ms = max(0, int((perf_counter() - translation_began) * 1000))
            if await _active_user_id(db, token) != user_id:
                await _error(websocket, "session_invalid", "Session is no longer valid", False)
                await _close(websocket, 1008)
                return False
            if start.save_history:
                assert start.session_id is not None and request_id is not None and fingerprint is not None
                saved = await save_translation(
                    db, user_id, start.session_id, start.target_language, request_id, fingerprint,
                    transcription.text, translated_text, detected_source,
                )
                original = saved.original_text
                translated = saved.translated_text
                detected = saved.detected_language
                message_id = saved.id
            else:
                original = transcription.text
                translated = translated_text
                detected = detected_source
                message_id = None
    except AINoSpeechError:
        return await _error(websocket, "no_speech", "No speech detected", True)
    except AIProviderTimeout:
        return await _error(websocket, "provider_timeout", "AI provider timed out", True,
                            chunk_id=chunk_id if transcription else None,
                            original=transcription.text if transcription else None,
                            detected_language=detected_source)
    except AIProviderUnavailable:
        return await _error(websocket, "provider_unavailable", "AI provider unavailable", True,
                            chunk_id=chunk_id if transcription else None,
                            original=transcription.text if transcription else None,
                            detected_language=detected_source)
    except AIProviderFailure:
        return await _error(websocket, "provider_error", "AI processing failed", True,
                            chunk_id=chunk_id if transcription else None,
                            original=transcription.text if transcription else None,
                            detected_language=detected_source)
    except AIInputError:
        return await _error(websocket, "invalid_input", "Audio could not be processed", True)
    except TimeoutError:
        return await _error(websocket, "processing_timeout", "Processing timed out", True,
                            chunk_id=chunk_id if transcription else None,
                            original=transcription.text if transcription else None,
                            detected_language=detected_source)
    except (HistoryDisabled, HistoryNotFound, HistorySessionEnded, HistoryConflict, SQLAlchemyError) as exc:
        await db.rollback()
        return await _history_error(websocket, exc)
    except Exception as exc:
        logger.warning("WebSocket chunk processing failed (%s)", type(exc).__name__)
        await _error(websocket, "internal_error", "Processing failed", False)
        await _close(websocket, 1011)
        return False

    elapsed_ms = max(0, int((perf_counter() - began) * 1000))
    return await _send_result_and_speech(
        websocket,
        ResultMessage(
            chunk_id=chunk_id,
            original=original,
            translated=translated,
            detected_language=detected,
            language_detection_source="stt" if detected else "unknown",
            target_language=start.target_language,
            processing_time_ms=elapsed_ms,
            transcription_time_ms=transcription_time_ms,
            translation_time_ms=translation_time_ms,
            saved=True if start.save_history else None,
            message_id=message_id,
        ),
        start, db, token, user_id, settings,
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
        websocket.app.state.metrics.increment("connection_rejections")
        await _close(websocket, 1013)
        return

    metrics = websocket.app.state.metrics
    metrics.increment("ws_connections")
    metrics.increment("ws_active")
    ws_context_token = websocket_id_context.set(uuid4().hex)
    interim_task: asyncio.Task[None] | None = None
    auth_lock = asyncio.Lock()

    try:
        await websocket.accept()
        start: StartMessage | None = None
        service: AIService | None = None
        chunk_id = 0
        pending_request_id: UUID | None = None
        pending_interim: InterimAudioMessage | None = None
        discard_interim_binary = False
        interim_count = 0
        last_interim_at = -float("inf")
        latest_interim_revision: dict[UUID, int] = {}
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
                    async with auth_lock:
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
                        await _cancel_interim(interim_task)
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
                        if parsed.synthesize_speech and not tts_configured(settings):
                            if not await _error(websocket, "speech_unavailable", "Speech service is not configured", True):
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
                            service.metrics = metrics
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
                                interim_captions=(settings.ws_interim_enabled if start.interim_captions else None),
                            ),
                        ):
                            return
                        continue

                    if payload.get("type") == "interim_audio":
                        if pending_interim is not None or discard_interim_binary:
                            if not await _error(websocket, "invalid_state", "Interim audio is pending", True):
                                return
                            continue
                        try:
                            meta = InterimAudioMessage.model_validate(payload)
                        except ValidationError:
                            pending_request_id = None
                            discard_interim_binary = True
                            if not await _error(websocket, "invalid_message", "Invalid interim metadata", True):
                                return
                            continue
                        if start is None or not start.interim_captions or not settings.ws_interim_enabled or pending_request_id is not None:
                            pending_request_id = None
                            discard_interim_binary = True
                            if not await _send(websocket, InterimErrorMessage(
                                phrase_id=meta.phrase_id, revision=meta.revision,
                                code="interim_unavailable", message="Interim captions unavailable; final captions continue",
                            )):
                                return
                            continue
                        pending_interim = meta
                        continue

                    if payload.get("type") == "interim_cancel":
                        try:
                            cancelled = InterimCancelMessage.model_validate(payload)
                        except ValidationError:
                            if not await _error(websocket, "invalid_message", "Invalid interim cancel message", True):
                                return
                            continue
                        if pending_interim is not None and pending_interim.phrase_id == cancelled.phrase_id:
                            pending_interim = None
                            discard_interim_binary = True
                        if cancelled.phrase_id in latest_interim_revision:
                            await _cancel_interim(interim_task)
                            interim_task = None
                            latest_interim_revision.pop(cancelled.phrase_id, None)
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

                received_at = perf_counter()
                audio = message.get("bytes")
                if not isinstance(audio, bytes):
                    if not await _error(websocket, "invalid_message", "Invalid message", True):
                        return
                    continue
                if discard_interim_binary:
                    discard_interim_binary = False
                    continue
                if pending_interim is not None:
                    meta = pending_interim
                    pending_interim = None
                    code: str | None = None
                    if len(audio) > settings.ws_interim_max_audio_bytes:
                        code = "audio_too_large"
                    else:
                        try:
                            validate_interim_wav(audio, settings.ws_interim_max_audio_bytes)
                        except InvalidAudioChunk:
                            code = "invalid_audio"
                    if code is None and interim_count >= settings.ws_interim_max_requests:
                        code = "interim_limit"
                    if code is None and perf_counter() - last_interim_at < settings.ws_interim_min_interval_seconds:
                        code = "interim_rate_limit"
                    if code is None and interim_task is not None and not interim_task.done():
                        code = "interim_busy"
                    if code is None and meta.revision <= latest_interim_revision.get(meta.phrase_id, 0):
                        code = "stale_revision"
                    if code is not None:
                        if not await _send(websocket, InterimErrorMessage(
                            phrase_id=meta.phrase_id, revision=meta.revision,
                            code=code, message="Interim caption skipped; final captions continue",
                        )):
                            return
                        continue
                    assert start is not None and service is not None
                    interim_count += 1
                    last_interim_at = perf_counter()
                    latest_interim_revision[meta.phrase_id] = meta.revision
                    # Only one snapshot runs at a time; final WAV cancels it before processing.
                    interim_task = asyncio.create_task(_process_interim(
                        websocket, db, auth_lock, token, user_id, service, start, meta, audio, settings,
                    ))
                    continue
                if start is None or service is None:
                    if not await _error(websocket, "invalid_state", "Send start before audio", True):
                        return
                    continue
                await _cancel_interim(interim_task)
                interim_task = None
                latest_interim_revision.clear()
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

                logger.debug(
                    "WebSocket audio accepted chunk_id=%d bytes=%d validation_ms=%d",
                    chunk_id + 1, len(audio), max(0, int((perf_counter() - received_at) * 1000)),
                )

                chunk_id += 1
                request_id = pending_request_id
                pending_request_id = None
                if not await _send(websocket, ProcessingMessage(chunk_id=chunk_id)):
                    return
                chunk_context_token = chunk_id_context.set(chunk_id)
                try:
                    if not await _process_chunk(
                        websocket, db, token, user_id, service, start, audio, chunk_id, settings, request_id
                    ):
                        return
                finally:
                    chunk_id_context.reset(chunk_context_token)
    except (WebSocketDisconnect, OSError, RuntimeError):
        return
    finally:
        await _cancel_interim(interim_task)
        websocket_id_context.reset(ws_context_token)
        metrics.increment("ws_active", -1)
        await registry.release(user_id)
