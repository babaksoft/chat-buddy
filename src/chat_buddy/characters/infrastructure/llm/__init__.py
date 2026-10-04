"""Lazy provider infrastructure."""

from chat_buddy.characters.infrastructure.llm.configured_providers import (
    create_model_registry,
)
from chat_buddy.characters.infrastructure.llm.ollama_gateway import OllamaGateway
from chat_buddy.characters.infrastructure.llm.registry import ConfiguredModelRegistry
from chat_buddy.characters.infrastructure.llm.token_counter import (
    OllamaTokenCounter,
    Utf8TokenCounter,
)

__all__ = [
    "ConfiguredModelRegistry",
    "OllamaGateway",
    "OllamaTokenCounter",
    "Utf8TokenCounter",
    "create_model_registry",
]
