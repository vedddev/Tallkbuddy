"""Manual, billable smoke test; excluded unless explicitly enabled."""

import asyncio
import os

import pytest

from app.ai.service import ai_service_context
from app.core.config import Settings


@pytest.mark.live_groq
def test_live_translation_smoke() -> None:
    if os.getenv("RUN_LIVE_GROQ_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_GROQ_TESTS=1 to allow a billable Groq request")
    settings = Settings()
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY is not configured")

    async def exercise() -> None:
        async with ai_service_context(settings) as service:
            result = await service.translate("Hello", "fr")
            assert result.original_text == "Hello"
            assert result.translated_text.strip()

    asyncio.run(exercise())
