"""Database operations for owned history and idempotent opt-in saves."""

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TranslationMessage, TranslationSession, UserPreference
from app.history.schemas import (
    CreateTranslationSession,
    MessagePage,
    PreferenceResponse,
    PreferenceUpdate,
    SessionDetail,
    SessionPage,
    TranslationMessageResponse,
    TranslationSessionResponse,
)


DEFAULT_SOURCE_LANGUAGE = "auto"
DEFAULT_TARGET_LANGUAGE = "en"
DEFAULT_SPEECH_RATE = 1.0


class HistoryError(Exception):
    status_code = 409
    public_detail = "History operation failed"


class HistoryNotFound(HistoryError):
    status_code = 404
    public_detail = "Translation session not found"


class HistoryDisabled(HistoryError):
    status_code = 409
    public_detail = "Enable history saving in preferences"


class HistoryConflict(HistoryError):
    status_code = 409
    public_detail = "History request conflicts with an existing result"


class HistorySessionEnded(HistoryError):
    status_code = 409
    public_detail = "Translation session has ended"


def fingerprint_text(text: str, target_language: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"text\x00")
    digest.update(target_language.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def fingerprint_audio(audio: bytes, target_language: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"audio\x00")
    digest.update(target_language.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(audio)
    return digest.hexdigest()


async def get_preference_record(db: AsyncSession, user_id: UUID) -> UserPreference | None:
    return await db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))


async def get_preferences(db: AsyncSession, user_id: UUID) -> PreferenceResponse:
    record = await get_preference_record(db, user_id)
    if record is None:
        return PreferenceResponse(
            source_language=DEFAULT_SOURCE_LANGUAGE,
            target_language=DEFAULT_TARGET_LANGUAGE,
            speech_rate=DEFAULT_SPEECH_RATE,
            save_history_enabled=False,
        )
    return PreferenceResponse.model_validate(
        {
            "source_language": record.source_language,
            "target_language": record.target_language,
            "speech_rate": record.speech_rate,
            "save_history_enabled": record.save_history_enabled,
        }
    )


async def update_preferences(
    db: AsyncSession, user_id: UUID, update: PreferenceUpdate
) -> PreferenceResponse:
    values = update.model_dump(exclude_unset=True)
    record = await get_preference_record(db, user_id)
    if record is None:
        defaults = (await get_preferences(db, user_id)).model_dump()
        record = UserPreference(user_id=user_id, **{**defaults, **values})
        db.add(record)
    else:
        for name, value in values.items():
            setattr(record, name, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        record = await get_preference_record(db, user_id)
        if record is None:
            raise
        for name, value in values.items():
            setattr(record, name, value)
        await db.commit()
    return await get_preferences(db, user_id)


async def get_owned_session(
    db: AsyncSession, user_id: UUID, session_id: UUID
) -> TranslationSession:
    record = await db.scalar(
        select(TranslationSession).where(
            TranslationSession.id == session_id, TranslationSession.user_id == user_id
        )
    )
    if record is None:
        raise HistoryNotFound
    return record


async def create_translation_session(
    db: AsyncSession, user_id: UUID, payload: CreateTranslationSession
) -> TranslationSession:
    preferences = await get_preferences(db, user_id)
    record = TranslationSession(
        user_id=user_id,
        title=payload.title,
        source_language=payload.source_language or preferences.source_language,
        target_language=payload.target_language or preferences.target_language,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def update_session_title(
    db: AsyncSession, user_id: UUID, session_id: UUID, title: str | None
) -> TranslationSession:
    record = await get_owned_session(db, user_id, session_id)
    record.title = title
    await db.commit()
    await db.refresh(record)
    return record


async def end_translation_session(
    db: AsyncSession, user_id: UUID, session_id: UUID
) -> TranslationSession:
    record = await get_owned_session(db, user_id, session_id)
    if record.ended_at is None:
        record.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(record)
    return record


async def list_sessions(
    db: AsyncSession, user_id: UUID, limit: int, offset: int, order: str
) -> SessionPage:
    total = await db.scalar(
        select(func.count()).select_from(TranslationSession).where(TranslationSession.user_id == user_id)
    )
    direction = (
        (TranslationSession.started_at.desc(), TranslationSession.id.desc())
        if order == "newest"
        else (TranslationSession.started_at.asc(), TranslationSession.id.asc())
    )
    records = (
        await db.scalars(
            select(TranslationSession)
            .where(TranslationSession.user_id == user_id)
            .order_by(*direction)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return SessionPage(total=total or 0, limit=limit, offset=offset, items=list(records))


async def get_session_detail(
    db: AsyncSession, user_id: UUID, session_id: UUID, limit: int, offset: int, order: str
) -> SessionDetail:
    record = await get_owned_session(db, user_id, session_id)
    total = await db.scalar(
        select(func.count())
        .select_from(TranslationMessage)
        .where(TranslationMessage.session_id == session_id)
    )
    direction = (
        (TranslationMessage.created_at.desc(), TranslationMessage.id.desc())
        if order == "newest"
        else (TranslationMessage.created_at.asc(), TranslationMessage.id.asc())
    )
    messages = (
        await db.scalars(
            select(TranslationMessage)
            .where(TranslationMessage.session_id == session_id)
            .order_by(*direction)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return SessionDetail(
        session=TranslationSessionResponse.model_validate(record),
        messages=MessagePage(
            total=total or 0,
            limit=limit,
            offset=offset,
            items=[TranslationMessageResponse.model_validate(message) for message in messages],
        ),
    )


async def delete_session(db: AsyncSession, user_id: UUID, session_id: UUID) -> None:
    record = await get_owned_session(db, user_id, session_id)
    await db.execute(delete(TranslationMessage).where(TranslationMessage.session_id == session_id))
    await db.delete(record)
    await db.commit()


async def clear_history(db: AsyncSession, user_id: UUID) -> int:
    count = await db.scalar(
        select(func.count()).select_from(TranslationSession).where(TranslationSession.user_id == user_id)
    )
    owned_ids = select(TranslationSession.id).where(TranslationSession.user_id == user_id)
    await db.execute(delete(TranslationMessage).where(TranslationMessage.session_id.in_(owned_ids)))
    await db.execute(delete(TranslationSession).where(TranslationSession.user_id == user_id))
    await db.commit()
    return count or 0


async def require_saving_allowed(
    db: AsyncSession, user_id: UUID, session_id: UUID, target_language: str
) -> TranslationSession:
    preferences = await get_preference_record(db, user_id)
    if preferences is None or not preferences.save_history_enabled:
        raise HistoryDisabled
    record = await get_owned_session(db, user_id, session_id)
    if record.ended_at is not None:
        raise HistorySessionEnded
    if record.target_language != target_language:
        raise HistoryConflict
    return record


async def get_saved_message(
    db: AsyncSession,
    user_id: UUID,
    session_id: UUID,
    target_language: str,
    idempotency_key: UUID,
    fingerprint: str,
) -> TranslationMessage | None:
    await require_saving_allowed(db, user_id, session_id, target_language)
    record = await db.scalar(
        select(TranslationMessage).where(
            TranslationMessage.session_id == session_id,
            TranslationMessage.idempotency_key == str(idempotency_key),
        )
    )
    if record is not None and record.request_fingerprint != fingerprint:
        raise HistoryConflict
    return record


async def save_translation(
    db: AsyncSession,
    user_id: UUID,
    session_id: UUID,
    target_language: str,
    idempotency_key: UUID,
    fingerprint: str,
    original_text: str,
    translated_text: str,
    detected_language: str | None,
) -> TranslationMessage:
    await require_saving_allowed(db, user_id, session_id, target_language)
    record = TranslationMessage(
        session_id=session_id,
        original_text=original_text,
        translated_text=translated_text,
        detected_language=detected_language,
        idempotency_key=str(idempotency_key),
        request_fingerprint=fingerprint,
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_saved_message(
            db, user_id, session_id, target_language, idempotency_key, fingerprint
        )
        if existing is None:
            raise
        return existing
    await db.refresh(record)
    return record
