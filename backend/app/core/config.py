"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
LOCAL_DEVELOPMENT_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


class Settings(BaseSettings):
    """Validated configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TalkBuddy API"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: list[str] = Field(default_factory=list)
    database_url: str | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    database_command_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    auth_session_days: int = Field(default=7, ge=1, le=30)
    auth_login_rate_limit: int = Field(default=10, ge=1)
    auth_register_rate_limit: int = Field(default=5, ge=1)
    auth_rate_window_seconds: int = Field(default=60, ge=1)
    auth_cookie_secure: bool | None = None
    auth_cookie_samesite: Literal["lax", "strict"] = "lax"
    groq_api_key: SecretStr | None = None
    groq_transcription_model: str = "whisper-large-v3-turbo"
    groq_translation_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = Field(default=45.0, ge=1.0, le=120.0)
    groq_max_retries: int = Field(default=2, ge=0, le=3)
    ai_max_audio_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=25_000_000)
    ai_max_text_chars: int = Field(default=5000, ge=1, le=20000)
    ai_max_concurrent_provider_calls: int = Field(default=8, ge=1, le=100)
    ai_provider_queue_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    ws_max_audio_bytes: int = Field(default=1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    ws_max_control_bytes: int = Field(default=2048, ge=128, le=16384)
    ws_max_connections_per_user: int = Field(default=2, ge=1, le=20)
    ws_max_chunks: int = Field(default=100, ge=1, le=10000)
    ws_idle_timeout_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)
    ws_processing_timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0)

    @property
    def cookie_secure(self) -> bool:
        """Require HTTPS cookies in production while allowing local HTTP development."""

        return self.app_env == "production" or self.auth_cookie_secure is True

    @property
    def allowed_origins(self) -> list[str]:
        """Trust the two local Vite origins only in development."""

        origins = [*self.cors_origins]
        if self.app_env == "development":
            origins.extend(LOCAL_DEVELOPMENT_ORIGINS)
        return list(dict.fromkeys(origins))


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""

    return Settings()
