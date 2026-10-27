"""Storyline prompt ordering and exclusion behavior."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from chat_buddy.characters.application import StorylineContextBudgeter
from chat_buddy.characters.domain import (
    CompletedTurn,
    ContextCapacityError,
    ContinuityLifecycle,
    ConversationScope,
    EffectiveGeneration,
    EligibleContext,
    GenerationConfiguration,
    Identity,
    IdentityDetails,
    MemoryRevision,
    Message,
    ModelDescriptor,
    Persona,
    PersonaCore,
    PromptMessage,
    RelationshipIntent,
    ResponseStyleSnapshot,
    Scene,
    SceneDetails,
    StartingOrigins,
    StartingRelationship,
    Storyline,
    StorylineMemory,
)
from chat_buddy.characters.prompts import assemble_storyline_prompt


class MessageCounter:
    """Count one token per complete provider message."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Return the number of provider messages.

        Args:
            messages:
                Complete prompt candidate.

        Returns:
            Number of indivisible messages.
        """

        return len(messages)


def test_storyline_prompt_uses_exact_scene_blocks_and_selected_memory() -> None:
    """Order memory before scene state without titles or other scenes."""

    identity_id, persona_id, storyline_id, conversation_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    scope = ConversationScope(
        identity_id=identity_id,
        persona_id=persona_id,
        continuity_id=storyline_id,
        conversation_id=conversation_id,
    )
    identity = Identity(
        id=identity_id,
        details=IdentityDetails(name="Traveler"),
        is_default=False,
        is_frozen=True,
        revision=1,
    )
    persona = Persona(
        id=persona_id,
        core=PersonaCore(name="Conductor", definition="A careful conductor."),
        is_frozen=True,
        revision=1,
    )
    relationship = StartingRelationship(
        intent=RelationshipIntent.PLATONIC,
        social="stranger",
        romantic="none",
        dynamic="neutral",
        trust="unknown",
        affection="neutral",
        boundaries=(),
        origins=StartingOrigins(
            social="default",
            romantic="default",
            dynamic="default",
            trust="default",
            affection="default",
            boundaries="default",
        ),
    )
    storyline = Storyline(
        id=storyline_id,
        identity_id=identity_id,
        persona_id=persona_id,
        name="Secret title that must stay out",
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=relationship,
        revision=1,
    )
    scene = Scene(
        id=uuid4(),
        scope=scope,
        position=1,
        details=SceneDetails(
            title="Hidden presentation title",
            setup="They wait beside the midnight train.",
            response_style=ResponseStyleSnapshot(
                name="storyline.quiet",
                version="1.0.0",
                instruction="Reply with restrained warmth.",
            ),
        ),
        setup_locked=True,
    )
    messages = (
        Message(
            id=uuid4(),
            scope=scope,
            sequence=1,
            role="user",
            content="Is it time?",
            created_at=datetime.now(UTC),
        ),
        Message(
            id=uuid4(),
            scope=scope,
            sequence=2,
            role="persona",
            content="Almost.",
            created_at=datetime.now(UTC),
        ),
    )
    memory = StorylineMemory.model_construct(
        id=uuid4(),
        continuity_id=storyline.id,
        current_revision_id=uuid4(),
        revisions=(
            MemoryRevision.model_construct(
                subject="departure time",
                content="The train leaves at midnight.",
            ),
        ),
        evidence=(),
    )

    prompt = assemble_storyline_prompt(
        persona,
        identity,
        storyline,
        scene,
        messages,
        current_input="I am ready.",
        summary="They agreed to depart.",
        memories=(memory,),
    )

    assert [message.content.split("\n", 1)[0] for message in prompt[:7]] == [
        "Persona core:",
        "Identity:",
        "Relationship intent and starting state:",
        "Continuity memory:",
        "Scene setup:",
        "Response style:",
        "Conversation summary:",
    ]
    assert [message.role for message in prompt] == ["system"] * 7 + [
        "user",
        "assistant",
        "user",
    ]
    rendered = "\n".join(message.content for message in prompt)
    assert "Hidden presentation title" not in rendered
    assert "Secret title that must stay out" not in rendered
    assert "The train leaves at midnight." in rendered
    assert "unselected alternative" not in rendered
    assert "partial attempt" not in rendered

    context = EligibleContext(
        summary=None,
        uncovered_turns=(CompletedTurn(user=messages[0], persona=messages[1]),),
        current_input="I am ready.",
    )
    exact_generation = EffectiveGeneration(
        model=ModelDescriptor(
            provider="fake",
            model="exact",
            context_tokens=73,
            output_tokens=1,
            capabilities=frozenset({"response"}),
        ),
        configuration=GenerationConfiguration(max_output_tokens=1),
        capability="response",
        input_tokens=72,
    )
    selection = StorylineContextBudgeter().assemble(
        persona,
        identity,
        storyline,
        scene,
        context,
        exact_generation,
        MessageCounter(),
        (memory,),
    )
    assert all(
        not message.content.startswith("Continuity memory:")
        for message in selection.prompt
    )
    with pytest.raises(ContextCapacityError, match="Mandatory Storyline"):
        StorylineContextBudgeter().assemble(
            persona,
            identity,
            storyline,
            scene,
            context,
            exact_generation.model_copy(update={"input_tokens": 71}),
            MessageCounter(),
            (memory,),
        )
