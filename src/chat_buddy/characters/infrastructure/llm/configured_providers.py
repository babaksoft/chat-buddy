"""Explicit lazy composition of independently configured local capabilities."""

import os

from chat_buddy.characters.domain import GenerationCapability, ModelDescriptor
from chat_buddy.characters.infrastructure.llm.ollama_gateway import OllamaGateway
from chat_buddy.characters.infrastructure.llm.registry import ConfiguredModelRegistry
from chat_buddy.characters.infrastructure.llm.token_counter import OllamaTokenCounter


def create_model_registry() -> ConfiguredModelRegistry:
    """Compose local providers only when explicitly requested.

    Environment settings are Characters-owned and read at composition time.
    Neither importing this module nor selecting the Chat route creates clients.

    Returns:
        Registry supporting independently selected response, summary, and memory
        extraction models.

    Raises:
        ValueError:
            If configured token limits or model names are invalid.
    """

    response_model = os.environ.get("CHARACTERS_RESPONSE_MODEL", "gpt-oss:20b-cloud")
    summary_model = os.environ.get("CHARACTERS_SUMMARY_MODEL", "gpt-oss:20b-cloud")
    memory_model = os.environ.get(
        "CHARACTERS_MEMORY_EXTRACTION_MODEL", "gpt-oss:20b-cloud"
    )
    evolution_model = os.environ.get("CHARACTERS_EVOLUTION_MODEL", "gpt-oss:20b-cloud")
    context = int(os.environ.get("CHARACTERS_CONTEXT_TOKENS", "32768"))
    output = int(os.environ.get("CHARACTERS_OUTPUT_TOKENS", "4096"))

    model_capabilities: dict[str, set[GenerationCapability]] = {}
    model_capabilities.setdefault(response_model, set()).add("response")
    model_capabilities.setdefault(summary_model, set()).add("summary")
    model_capabilities.setdefault(memory_model, set()).add("memory_extraction")
    model_capabilities.setdefault(evolution_model, set()).add("evolution")
    models = tuple(
        ModelDescriptor(
            provider="ollama",
            model=name,
            context_tokens=context,
            output_tokens=output,
            capabilities=frozenset(capabilities),
            parameters=frozenset({"temperature", "top_p", "seed"}),
        )
        for name, capabilities in model_capabilities.items()
    )

    gateway = OllamaGateway(
        host=os.environ.get("CHARACTERS_OLLAMA_ENDPOINT_URL", "http://localhost:11434")
    )

    return ConfiguredModelRegistry(
        models=models,
        responses={"ollama": gateway},
        summaries={"ollama": gateway},
        memory_extractions={"ollama": gateway},
        evolutions={"ollama": gateway},
        counters={"ollama": OllamaTokenCounter()},
        defaults={
            "response": ("ollama", response_model),
            "summary": ("ollama", summary_model),
            "memory_extraction": ("ollama", memory_model),
            "evolution": ("ollama", evolution_model),
        },
    )
