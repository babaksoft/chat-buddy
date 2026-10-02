"""Explicitly enabled, networked, and billable OpenAI smoke coverage."""

import os

import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    GenerationConfiguration,
    ModelId,
)
from chat_buddy.chat.infrastructure.llm import OpenAIGateway


@pytest.mark.openai_smoke
def test_live_openai_response() -> None:
    """Generate a minimal live response only under both explicit opt-ins."""

    enabled = os.getenv("CHAT_OPENAI_SMOKE_TEST", "").strip().lower() == "true"
    api_key = os.getenv("CHAT_OPENAI_API_KEY", "").strip()
    if not enabled or not api_key:
        pytest.skip("Set CHAT_OPENAI_SMOKE_TEST=true and CHAT_OPENAI_API_KEY to run.")

    response = OpenAIGateway(api_key=api_key).generate(
        [ChatMessage(ChatRole.USER, "Reply with exactly: smoke-ok")],
        ModelId("gpt-5.6-luna"),
        GenerationConfiguration(max_output_tokens=32),
    )

    assert response.strip()
