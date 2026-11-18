"""Request and response models for preferences and translation history."""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.languages import parse_target_language


def parse_source_language(value: str) -> str:
    return "auto" if value.strip().lower() == "auto" else parse_target_language(value)


class PreferenceResponse(BaseModel):
    source_language: str
    target_language: str
    speech_rate: float
    save_history_enabled: bool


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_language: str | None = None
    target_language: str | None = None
    speech_rate: float | None = Field(default=None, ge=0.5, le=2.0, allow_inf_nan=False)
    save_history_enabled: bool | None = None

    @field_validator("source_language")
    @classmethod
    def valid_source(cls, value: str | None) -> str | None:
        return parse_source_language(value) if value is not None else None

    @field_validator("target_language")
    @classmethod
    def valid_target(cls, value: str | None) -> str | None:
        return parse_target_language(value) if value is not None else None

    @model_validator(mode="after")
    def nonempty_update(self) -> "PreferenceUpdate":
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Provide one or more non-null preference values")
        return self


class CreateTranslationSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=255)
    source_language: str | None = None
    target_language: str | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Title must not be blank")
        return cleaned

    @field_validator("source_language")
    @classmethod
    def valid_source(cls, value: str | None) -> str | None:
        return parse_source_language(value) if value is not None else None

    @field_validator("target_language")
    @classmethod
    def valid_target(cls, value: str | None) -> str | None:
        return parse_target_language(value) if value is not None else None


class UpdateSessionTitle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(max_length=255)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Title must not be blank")
        return cleaned


class TranslationSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    source_language: str
    target_language: str
    started_at: datetime
    ended_at: datetime | None

    @field_validator("started_at", "ended_at")
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class TranslationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_text: str
    translated_text: str
    detected_language: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class SessionPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TranslationSessionResponse]


class MessagePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TranslationMessageResponse]


class SessionDetail(BaseModel):
    session: TranslationSessionResponse
    messages: MessagePage


class ClearHistoryResponse(BaseModel):
    deleted_sessions: int
