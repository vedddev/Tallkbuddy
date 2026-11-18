"""Request and response shapes for AI endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.ai.languages import parse_target_language


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1)
    target_language: str
    save_history: bool = False
    session_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must not be empty")
        return value

    @field_validator("target_language")
    @classmethod
    def supported_language(cls, value: str) -> str:
        return parse_target_language(value)


class TranscriptionResponse(BaseModel):
    text: str
    detected_language: str | None


class TranslationResponse(BaseModel):
    original_text: str
    translated_text: str
    target_language: str
    saved: bool | None = None
    message_id: UUID | None = None


class SpeechTranslationResponse(BaseModel):
    original_text: str
    translated_text: str
    detected_language: str | None
    target_language: str
    saved: bool | None = None
    message_id: UUID | None = None
