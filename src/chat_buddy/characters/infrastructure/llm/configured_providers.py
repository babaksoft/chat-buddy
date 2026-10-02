"""Explicit lazy composition of independently configured local capabilities."""

import os

from chat_buddy.characters.domain.llm import ModelCapabilities
from chat_buddy.characters.infrastructure.llm.ollama_gateway import OllamaGateway
from chat_buddy.characters.infrastructure.llm.resolver import ConfiguredModelResolver
from chat_buddy.characters.infrastructure.llm.token_counter import Utf8TokenCounter


def create_model_resolver() -> ConfiguredModelResolver:
    """Compose Characters local providers only when explicitly requested.

    Environment settings are Characters-owned and read at composition time.
    Neither importing this module nor selecting the Chat route creates clients.

    Returns:
        Resolver supporting independently selected response and summary models.

    Raises:
        ValueError:
            If configured token limits or model names are invalid.
    """

    response_model = os.environ.get("CHARACTERS_RESPONSE_MODEL", "mistral")
    summary_model = os.environ.get("CHARACTERS_SUMMARY_MODEL", "mistral")
    context = int(os.environ.get("CHARACTERS_CONTEXT_TOKENS", "8192"))
    output = int(os.environ.get("CHARACTERS_OUTPUT_TOKENS", "1024"))
    models = tuple(
        ModelCapabilities(
            provider="ollama",
            model=name,
            context_tokens=context,
            output_tokens=output,
            capabilities=frozenset({"response", "summary"}),
            parameters=frozenset({"temperature", "top_p", "seed"}),
        )
        for name in dict.fromkeys((response_model, summary_model))
    )
    gateway = OllamaGateway(
        host=os.environ.get("CHARACTERS_OLLAMA_ENDPOINT_URL", "http://localhost:11434")
    )
    return ConfiguredModelResolver(
        models=models,
        responses={"ollama": gateway},
        summaries={"ollama": gateway},
        counters={"ollama": Utf8TokenCounter()},
        defaults={
            "response": ("ollama", response_model),
            "summary": ("ollama", summary_model),
        },
    )
