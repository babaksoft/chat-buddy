"""Chat infrastructure settings and environment-backed cloud opt-in."""

import os

# Database settings
DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/chat_buddy"

# LLM settings
OLLAMA_ENDPOINT_URL = "http://172.31.80.1:11434"
OLLAMA_PROVIDER_ID = "ollama"
OLLAMA_PROVIDER_NAME = "Ollama"
CHAT_MODEL = "gpt-oss:20b-cloud"
CHAT_MODELS = (CHAT_MODEL,)
UTILITY_MODEL = "gpt-oss:20b-cloud"
MODEL_CONTEXT_WINDOW = 32_768
MODEL_DEFAULT_OUTPUT_TOKEN_RESERVE = 4_096
PROMPT_OVERHEAD_TOKENS = 64  # Reserved for Ollama system prompt and formatting tokens
SUMMARY_TRIGGER_RATIO = 0.85
MINIMUM_RECENT_TURNS = 2

# OpenAI response-only provider settings
OPENAI_PROVIDER_ID = "openai"
OPENAI_PROVIDER_NAME = "OpenAI"
OPENAI_APPLICATION_PROMPT_LIMIT = 65_536


def is_openai_enabled() -> bool:
    """Return whether the explicit Chat OpenAI opt-in is enabled.

    Returns:
        ``True`` only when ``CHAT_OPENAI_ENABLED`` is set to ``true``.
    """

    return os.getenv("CHAT_OPENAI_ENABLED", "").strip().lower() == "true"


def get_openai_api_key() -> str | None:
    """Read and normalize the Chat-specific OpenAI credential.

    Returns:
        Non-blank credential, or ``None`` when absent or blank.
    """

    value = os.getenv("CHAT_OPENAI_API_KEY")
    if value is None or not value.strip():
        return None
    return value.strip()
