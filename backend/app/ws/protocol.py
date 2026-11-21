"""Control and server messages for chunked speech translation."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.ai.languages import parse_target_language


class StartMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["start"]
    target_language: str
    source_language: str | None = None
    audio_format: Literal["wav"]
    save_history: bool = False
    session_id: UUID | None = None
    synthesize_speech: bool = False

    @field_validator("target_language")
    @classmethod
    def target_is_supported(cls, value: str) -> str:
        return parse_target_language(value)

    @field_validator("source_language")
    @classmethod
    def source_is_supported(cls, value: str | None) -> str | None:
        return parse_target_language(value) if value is not None else None


class StopMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["stop"]


class ChunkMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["chunk"]
    request_id: UUID


class ReadyMessage(BaseModel):
    type: Literal["ready"] = "ready"
    target_language: str
    source_language: str | None
    audio_format: Literal["wav"] = "wav"


class ProcessingMessage(BaseModel):
    type: Literal["processing"] = "processing"
    chunk_id: int


class ResultMessage(BaseModel):
    type: Literal["result"] = "result"
    chunk_id: int
    original: str
    translated: str
    detected_language: str | None
    language_detection_source: Literal["stt", "unknown"] | None = None
    target_language: str
    processing_time_ms: int
    transcription_time_ms: int | None = None
    translation_time_ms: int | None = None
    saved: bool | None = None
    message_id: UUID | None = None


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    recoverable: bool
    chunk_id: int | None = None
    original: str | None = None
    detected_language: str | None = None
    language_detection_source: Literal["stt", "unknown"] | None = None


class SpeechAudioMessage(BaseModel):
    type: Literal["speech_audio"] = "speech_audio"
    chunk_id: int
    audio_format: Literal["wav"] = "wav"
    audio_base64: str
    preparation_time_ms: int


class SpeechErrorMessage(BaseModel):
    type: Literal["speech_error"] = "speech_error"
    chunk_id: int
    code: str
    message: str
