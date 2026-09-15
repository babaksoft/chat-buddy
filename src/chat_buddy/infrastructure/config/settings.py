"""Compatibility re-exports for configuration moved into owned packages."""

from chat_buddy.chat.infrastructure.config.settings import (
    CHAT_MODEL,
    DATABASE_URL,
    MEMORY_EXTRACTION_INTERVAL,
    MODEL_CONTEXT_WINDOW,
    OLLAMA_ENDPOINT_URL,
    PROMPT_OVERHEAD_TOKENS,
    SUMMARY_TRIGGER_RATIO,
    UTILITY_MODEL,
)
from chat_buddy.shared.config.settings import LOG_DIR, LOG_FILE, LOG_LEVEL, PKG_ROOT

__all__ = [
    "CHAT_MODEL",
    "DATABASE_URL",
    "LOG_DIR",
    "LOG_FILE",
    "LOG_LEVEL",
    "MEMORY_EXTRACTION_INTERVAL",
    "MODEL_CONTEXT_WINDOW",
    "OLLAMA_ENDPOINT_URL",
    "PKG_ROOT",
    "PROMPT_OVERHEAD_TOKENS",
    "SUMMARY_TRIGGER_RATIO",
    "UTILITY_MODEL",
]
