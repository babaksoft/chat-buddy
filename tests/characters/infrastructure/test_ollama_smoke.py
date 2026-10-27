"""Explicitly enabled local Characters Ollama streaming smoke coverage."""

import os
from contextlib import closing

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import PromptMessage, SubmittedInput
from chat_buddy.characters.infrastructure import create_conversation_service
from chat_buddy.characters.infrastructure.llm import create_model_registry
from tests.characters_support import start


@pytest.mark.characters_ollama_smoke
def test_local_ollama_stream_persists_and_resumes(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Stream through production composition without touching development data.

    Args:
        characters_session_factory:
            Isolated Characters database with no Chat imports.
    """

    if os.environ.get("CHARACTERS_OLLAMA_SMOKE_TEST", "").lower() != "true":
        pytest.skip("Set CHARACTERS_OLLAMA_SMOKE_TEST=true with local models available")
    scope = start(characters_session_factory)
    service = create_conversation_service(characters_session_factory)
    attempt = service.send(scope, SubmittedInput(content="Say hello in one sentence."))
    with closing(service.stream(scope, attempt.id)) as stream:
        chunks = list(stream)
    assert chunks and "".join(chunks).strip()
    history = create_conversation_service(characters_session_factory).resume(scope)
    assert history.messages[-1].content == "".join(chunks)
    assert history.attempts[-1].status == "completed"
    assert history.attempts[-1].generation == attempt.generation


@pytest.mark.characters_ollama_smoke
def test_local_ollama_memory_extraction_returns_schema_constrained_json() -> None:
    """Exercise the separately configured structured utility capability."""

    if os.environ.get("CHARACTERS_OLLAMA_SMOKE_TEST", "").lower() != "true":
        pytest.skip("Set CHARACTERS_OLLAMA_SMOKE_TEST=true with local models available")
    registry = create_model_registry()
    generation = registry.resolve_default("memory_extraction")
    schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["operation"],
        "properties": {"operation": {"const": "no_change"}},
    }

    result = registry.memory_extraction_gateway(
        generation.model.provider
    ).extract_memory(
        (
            PromptMessage(
                role="system",
                content="Return the schema-constrained no_change object.",
            ),
        ),
        generation,
        schema,
    )

    assert '"no_change"' in result
