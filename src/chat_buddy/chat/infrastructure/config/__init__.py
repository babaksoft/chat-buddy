"""Configuration for Chat infrastructure adapters."""

from chat_buddy.chat.infrastructure.config.settings import (
    get_openai_api_key,
    is_openai_enabled,
)

__all__ = [
    "get_openai_api_key",
    "is_openai_enabled",
]
