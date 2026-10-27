"""Contextual Storyline delta prompt, parser, and adapter tests."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from chat_buddy.characters.domain import (
    CompletedTurn,
    ConversationScope,
    EffectiveGeneration,
    ExtractionBudget,
    GenerationConfiguration,
    InvalidProviderResponseError,
    MemoryAuthorship,
    MemoryExtractionContext,
    MemoryRevision,
    MemorySelectionResult,
    Message,
    ModelDescriptor,
    PromptMessage,
    ScenePosition,
    StorylineMemory,
    StrategyIdentity,
)
from chat_buddy.characters.infrastructure.llm import ContextualMemoryDeltaExtractor
from chat_buddy.characters.prompts import assemble_memory_extraction_prompt

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
SELECTION_ID = UUID("10000000-0000-0000-0000-000000000001")
SCENE_ID = UUID("20000000-0000-0000-0000-000000000001")
USER_ID = UUID("30000000-0000-0000-0000-000000000001")
PERSONA_MESSAGE_ID = UUID("40000000-0000-0000-0000-000000000001")
MEMORY_ID = UUID("50000000-0000-0000-0000-000000000001")
REVISION_ID = UUID("60000000-0000-0000-0000-000000000001")
EVIDENCE_ID = UUID("70000000-0000-0000-0000-000000000001")


class FakeMemoryGateway:
    """Capture a structured extraction request and return configured JSON."""

    def __init__(self, response: str) -> None:
        """Store one provider response.

        Args:
            response:
                Exact text returned by extraction.
        """

        self.response = response
        self.calls: list[
            tuple[tuple[PromptMessage, ...], EffectiveGeneration, dict[str, object]]
        ] = []

    def extract_memory(
        self,
        messages: tuple[PromptMessage, ...],
        generation: EffectiveGeneration,
        schema: dict[str, object],
    ) -> str:
        """Capture provider inputs and return configured text.

        Args:
            messages:
                Ordered strict prompt.
            generation:
                Effective extraction model.
            schema:
                Strict provider response schema.

        Returns:
            Configured response text.
        """

        self.calls.append((messages, generation, schema))
        return self.response


def _generation() -> EffectiveGeneration:
    """Build an independently resolved extraction generation.

    Returns:
        Effective utility-model selection.
    """

    model = ModelDescriptor(
        provider="fake",
        model="memory-model",
        context_tokens=1024,
        output_tokens=128,
        capabilities=frozenset({"memory_extraction"}),
    )
    return EffectiveGeneration(
        model=model,
        configuration=GenerationConfiguration(max_output_tokens=128),
        capability="memory_extraction",
        input_tokens=896,
    )


def _selection() -> MemorySelectionResult:
    """Build one deterministic snapshot with an included target memory.

    Returns:
        Minimal valid immutable selection.
    """

    scope = ConversationScope(
        identity_id=UUID("80000000-0000-0000-0000-000000000001"),
        persona_id=UUID("90000000-0000-0000-0000-000000000001"),
        continuity_id=UUID("a0000000-0000-0000-0000-000000000001"),
        conversation_id=UUID("b0000000-0000-0000-0000-000000000001"),
    )
    source = CompletedTurn(
        user=Message(
            id=USER_ID,
            scope=scope,
            sequence=1,
            role="user",
            content="My favorite tea is jasmine.",
            created_at=NOW,
        ),
        persona=Message(
            id=PERSONA_MESSAGE_ID,
            scope=scope,
            sequence=2,
            role="persona",
            content="I will remember that.",
            created_at=NOW,
        ),
    )
    position = ScenePosition(scene_id=SCENE_ID, position=2)
    source_evidence = type("Source", (), {"occurrence": position})()
    revision = MemoryRevision.model_construct(
        id=REVISION_ID,
        memory_id=MEMORY_ID,
        continuity_id=scope.continuity_id,
        revision=1,
        predecessor_id=None,
        subject="favorite tea",
        content="Their favorite tea is jasmine.",
        state="active",
        authorship=MemoryAuthorship.EXTRACTED,
        kind="extraction",
        source=source_evidence,
        created_at=NOW,
    )
    memory = StorylineMemory.model_construct(
        id=MEMORY_ID,
        continuity_id=scope.continuity_id,
        current_revision_id=REVISION_ID,
        revisions=(revision,),
        evidence=(),
    )
    context = MemoryExtractionContext.model_construct(
        scope=scope,
        scene=position,
        identity_label="Alex",
        persona_label="Rin",
        starting_relationship=None,
        scene_setup="A quiet kitchen.",
        summary=None,
        recent_turns=(),
        eligible_memories=(memory,),
        source_turn=source,
    )
    return MemorySelectionResult.model_construct(
        id=SELECTION_ID,
        selector=StrategyIdentity(name="baseline.selector", version="1.0.0"),
        context=context,
        included_turn_ids=(),
        omitted_turn_ids=(),
        included_memory_ids=(MEMORY_ID,),
        omitted_memory_ids=(),
        summary_included=False,
        prompt=(
            "[identity]\nAlex",
            (
                f"[memory:{MEMORY_ID}]\nSubject: favorite tea\n"
                "Content: Their favorite tea is jasmine."
            ),
            (
                f"[new evidence:{PERSONA_MESSAGE_ID}]\n"
                "User: My favorite tea is jasmine.\n"
                "Persona: I will remember that."
            ),
        ),
        token_count=100,
        budget=ExtractionBudget(input_tokens=512, fixed_overhead_tokens=32),
    )


def _evidence() -> dict[str, object]:
    """Return the exact source echo required in non-empty commands.

    Returns:
        JSON-compatible evidence reference.
    """

    return {
        "user_message_id": str(USER_ID),
        "persona_message_id": str(PERSONA_MESSAGE_ID),
        "occurrence": {"scene_id": str(SCENE_ID), "position": 2},
    }


@pytest.mark.parametrize(
    ("command", "expected_operation"),
    [
        (
            {
                "operation": "create",
                "subject": " favorite tea ",
                "content": " Their favorite tea is jasmine. ",
                "evidence": _evidence(),
            },
            "create",
        ),
        (
            {
                "operation": "reinforce",
                "target_memory_id": str(MEMORY_ID),
                "expected_revision_id": str(REVISION_ID),
                "content": "Their favorite tea is jasmine.",
                "evidence": _evidence(),
            },
            "reinforce",
        ),
        (
            {
                "operation": "supersede",
                "target_memory_id": str(MEMORY_ID),
                "expected_revision_id": str(REVISION_ID),
                "subject": "favorite tea",
                "content": "Their favorite tea is now oolong.",
                "evidence": _evidence(),
            },
            "supersede",
        ),
        (
            {
                "operation": "conflict",
                "target_memory_id": str(MEMORY_ID),
                "expected_revision_id": str(REVISION_ID),
                "subject": "favorite tea",
                "content": "Their favorite tea may be oolong.",
                "evidence": _evidence(),
            },
            "conflict",
        ),
        ({"operation": "no_change"}, "no_change"),
    ],
)
def test_extractor_parses_every_operation_and_attaches_provenance(
    command: dict[str, object], expected_operation: str
) -> None:
    """Parse every operation while attaching trusted source provenance.

    Args:
        command:
            Strict provider command.
        expected_operation:
            Expected typed domain discriminator.
    """

    gateway = FakeMemoryGateway(json.dumps({"commands": [command]}))
    extractor = ContextualMemoryDeltaExtractor(
        gateway,
        _generation(),
        id_factory=lambda: EVIDENCE_ID,
        clock=lambda: NOW,
    )

    delta = extractor.extract(_selection())

    assert delta.commands[0].operation == expected_operation
    assert delta.selection_id == SELECTION_ID
    assert delta.extractor == extractor.strategy_id
    assert len(gateway.calls) == 1
    if expected_operation != "no_change":
        evidence = delta.commands[0].evidence  # type: ignore[union-attr]
        assert evidence.id == EVIDENCE_ID
        assert evidence.extraction.model == "memory-model"
        assert evidence.extraction.prompt_schema_version == "1.0.0"
    if expected_operation == "create":
        assert delta.commands[0].subject == "favorite tea"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        json.dumps({"commands": [{"operation": "no_change", "extra": True}]}),
        json.dumps({"commands": [{"operation": "create", "subject": 1}]}),
        json.dumps({"commands": [{"operation": "invented"}]}),
        json.dumps(
            {"commands": [{"operation": "create", "subject": "x", "content": "y"}]}
        ),
        json.dumps({"commands": [{"operation": "no_change"}] * 17}),
    ],
)
def test_extractor_rejects_malformed_or_oversized_provider_output(
    response: str,
) -> None:
    """Reject malformed JSON, extra fields, invalid types, and schema violations.

    Args:
        response:
            Invalid provider text.
    """

    extractor = ContextualMemoryDeltaExtractor(
        FakeMemoryGateway(response), _generation()
    )

    with pytest.raises(InvalidProviderResponseError, match="invalid delta"):
        extractor.extract(_selection())


def test_extractor_rejects_invented_source_evidence() -> None:
    """Require every non-empty command to echo the exact new source turn."""

    evidence = _evidence()
    evidence["persona_message_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    response = json.dumps(
        {
            "commands": [
                {
                    "operation": "create",
                    "subject": "favorite tea",
                    "content": "Their favorite tea is jasmine.",
                    "evidence": evidence,
                }
            ]
        }
    )

    with pytest.raises(InvalidProviderResponseError, match="invalid delta"):
        ContextualMemoryDeltaExtractor(
            FakeMemoryGateway(response), _generation()
        ).extract(_selection())


def test_prompt_renders_the_exact_snapshot_and_separates_new_evidence() -> None:
    """Preserve selected blocks exactly and state the source/context boundary."""

    selection = _selection()
    schema: dict[str, object] = {"type": "object", "additionalProperties": False}

    messages = assemble_memory_extraction_prompt(selection, schema)

    assert len(messages) == 2
    assert "facts found only in older context" in messages[0].content
    assert (
        json.dumps(schema, sort_keys=True, separators=(",", ":")) in messages[0].content
    )
    assert messages[1].content.endswith("\n\n".join(selection.prompt))
    assert f"source_user_message_id={USER_ID}" in messages[1].content
    assert f"source_persona_message_id={PERSONA_MESSAGE_ID}" in messages[1].content
    assert "[context and new evidence]" in messages[1].content


def test_extractor_requires_the_memory_extraction_capability() -> None:
    """Reject accidental use of visible response generation settings."""

    generation = _generation().model_copy(update={"capability": "response"})

    with pytest.raises(ValueError, match="memory-extraction"):
        ContextualMemoryDeltaExtractor(FakeMemoryGateway("{}"), generation)
