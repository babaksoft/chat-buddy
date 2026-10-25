"""Storyline prompt ordering and exclusion behavior."""

from datetime import UTC, datetime
from uuid import uuid4

from chat_buddy.characters.domain import (
    ContinuityLifecycle,
    ConversationScope,
    Identity,
    IdentityDetails,
    Message,
    Persona,
    PersonaCore,
    RelationshipIntent,
    ResponseStyleSnapshot,
    Scene,
    SceneDetails,
    StartingOrigins,
    StartingRelationship,
    Storyline,
)
from chat_buddy.characters.prompts import assemble_storyline_prompt


def test_storyline_prompt_uses_exact_scene_blocks_and_excludes_future_inputs() -> None:
    """Order required blocks without titles, memory placeholders, or other scenes."""

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

    prompt = assemble_storyline_prompt(
        persona,
        identity,
        storyline,
        scene,
        messages,
        current_input="I am ready.",
        summary="They agreed to depart.",
    )

    assert [message.content.split("\n", 1)[0] for message in prompt[:6]] == [
        "Persona core:",
        "Identity:",
        "Relationship intent and starting state:",
        "Scene setup:",
        "Response style:",
        "Conversation summary:",
    ]
    assert [message.role for message in prompt] == ["system"] * 6 + [
        "user",
        "assistant",
        "user",
    ]
    rendered = "\n".join(message.content for message in prompt)
    assert "Hidden presentation title" not in rendered
    assert "Secret title that must stay out" not in rendered
    assert "memory" not in rendered.lower()
    assert "unselected alternative" not in rendered
    assert "partial attempt" not in rendered
