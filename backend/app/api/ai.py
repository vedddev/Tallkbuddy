"""Protected speech-to-text and translation endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.audio import read_audio_upload
from app.ai.languages import parse_target_language
from app.ai.schemas import (
    SpeechTranslationResponse,
    TranscriptionResponse,
    TranslationRequest,
    TranslationResponse,
)
from app.ai.service import AIService, AIInputError, AIServiceError, get_ai_service
from app.auth.dependencies import AuthenticatedSession, require_csrf
from app.api.auth import require_trusted_origin
from app.core.config import Settings
from app.db.session import get_db_session
from app.history.service import (
    fingerprint_audio,
    fingerprint_text,
    get_saved_message,
    save_translation,
)


router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(require_trusted_origin)])


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    _authenticated: AuthenticatedSession = Depends(require_csrf),
    service: AIService = Depends(get_ai_service),
) -> TranscriptionResponse:
    settings: Settings = request.app.state.settings
    data, filename = await read_audio_upload(audio, settings.ai_max_audio_bytes)
    return await service.transcribe(data, filename)


@router.post("/translate", response_model=TranslationResponse, response_model_exclude_none=True)
async def translate_text(
    request: Request,
    payload: TranslationRequest,
    authenticated: AuthenticatedSession = Depends(require_csrf),
    service: AIService = Depends(get_ai_service),
    db: AsyncSession = Depends(get_db_session),
    idempotency_key: UUID | None = Header(default=None, alias="Idempotency-Key"),
) -> TranslationResponse:
    settings: Settings = request.app.state.settings
    if len(payload.text) > settings.ai_max_text_chars:
        raise AIInputError("Text is too long")
    fingerprint = fingerprint_text(payload.text, payload.target_language)
    if payload.save_history:
        if payload.session_id is None or idempotency_key is None:
            raise HTTPException(status_code=422, detail="Saving requires session_id and Idempotency-Key")
        saved = await get_saved_message(
            db, authenticated.user.id, payload.session_id, payload.target_language,
            idempotency_key, fingerprint,
        )
        if saved is not None:
            return TranslationResponse(
                original_text=saved.original_text,
                translated_text=saved.translated_text,
                target_language=payload.target_language,
                saved=True,
                message_id=saved.id,
            )

    result = await service.translate(payload.text, payload.target_language)
    if payload.save_history:
        saved = await save_translation(
            db, authenticated.user.id, payload.session_id, payload.target_language,
            idempotency_key, fingerprint, result.original_text, result.translated_text, None,
        )
        result.original_text = saved.original_text
        result.translated_text = saved.translated_text
        result.saved = True
        result.message_id = saved.id
    return result


@router.post("/speech-translate", response_model=SpeechTranslationResponse, response_model_exclude_none=True)
async def speech_translate(
    request: Request,
    audio: UploadFile = File(...),
    target_language: str = Form(...),
    save_history: bool = Form(False),
    session_id: UUID | None = Form(None),
    authenticated: AuthenticatedSession = Depends(require_csrf),
    service: AIService = Depends(get_ai_service),
    db: AsyncSession = Depends(get_db_session),
    idempotency_key: UUID | None = Header(default=None, alias="Idempotency-Key"),
) -> SpeechTranslationResponse | JSONResponse:
    try:
        language = parse_target_language(target_language)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unsupported target language") from None
    settings: Settings = request.app.state.settings
    data, filename = await read_audio_upload(audio, settings.ai_max_audio_bytes)
    fingerprint = fingerprint_audio(data, language)
    if save_history:
        if session_id is None or idempotency_key is None:
            raise HTTPException(status_code=422, detail="Saving requires session_id and Idempotency-Key")
        saved = await get_saved_message(
            db, authenticated.user.id, session_id, language, idempotency_key, fingerprint
        )
        if saved is not None:
            return SpeechTranslationResponse(
                original_text=saved.original_text,
                translated_text=saved.translated_text,
                detected_language=saved.detected_language,
                target_language=language,
                saved=True,
                message_id=saved.id,
            )
    transcription = await service.transcribe(data, filename)
    if transcription.detected_language == language:
        translated_text = transcription.text
    else:
        try:
            translation = await service.translate(
                transcription.text, language, source_language=transcription.detected_language
            )
        except AIServiceError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.public_detail, "original_text": transcription.text,
                         "detected_language": transcription.detected_language},
            )
        translated_text = translation.translated_text
    if save_history:
        saved = await save_translation(
            db, authenticated.user.id, session_id, language, idempotency_key, fingerprint,
            transcription.text, translated_text, transcription.detected_language,
        )
        original_text = saved.original_text
        translated_text = saved.translated_text
        detected_language = saved.detected_language
        message_id = saved.id
    else:
        original_text = transcription.text
        detected_language = transcription.detected_language
        message_id = None
    return SpeechTranslationResponse(
        original_text=original_text,
        translated_text=translated_text,
        detected_language=detected_language,
        target_language=language,
        saved=True if save_history else None,
        message_id=message_id,
    )
