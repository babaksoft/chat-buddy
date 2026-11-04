"""Fixed Storyline response prompt blocks."""

from chat_buddy.characters.domain import (
    ContinuityMemory,
    Identity,
    Message,
    Persona,
    PersonaAdaptationProjection,
    PromptMessage,
    RelationshipProjection,
    ResponseStyle,
    Scene,
    Storyline,
)


def assemble_continuity_memory_blocks(
    memories: tuple[ContinuityMemory, ...],
) -> tuple[PromptMessage, ...]:
    """Render complete eligible memories as indivisible prompt blocks.

    Args:
        memories:
            Ordered selected continuity memories.

    Returns:
        One system message per complete current memory revision.
    """

    return tuple(
        PromptMessage(
            role="system",
            content=(
                "Continuity memory:\n"
                f"Subject: {memory.current.subject}\n"
                f"Content: {memory.current.content}"
            ),
        )
        for memory in memories
    )


def assemble_storyline_prompt(
    persona: Persona,
    identity: Identity,
    storyline: Storyline,
    scene: Scene,
    response_style: ResponseStyle,
    messages: tuple[Message, ...],
    current_input: str | None = None,
    summary: str | None = None,
    memories: tuple[ContinuityMemory, ...] = (),
    relationship: RelationshipProjection | None = None,
    adaptations: PersonaAdaptationProjection | None = None,
) -> tuple[PromptMessage, ...]:
    """Render one scene with selected memory and without foreign context.

    Args:
        persona:
            Frozen authored persona core.
        identity:
            Frozen authored identity.
        storyline:
            Owned starting relationship and lifecycle snapshot.
        scene:
            Exact immutable scene setup.
        response_style:
            Effective presentation snapshot reserved for this response.
        messages:
            Selected complete turns from this scene only.
        current_input:
            New input, absent when continuing an existing tail.
        summary:
            Compatible summary from this scene only.
        memories:
            Selected eligible continuity memories in response-strategy order.
        relationship:
            Current qualitative relationship projection when evolution is active.
        adaptations:
            Current continuity-local persona adaptations when evolution is active.

    Returns:
        Ordered provider input without titles, other scenes, or partial output.
    """

    ownership_blocks = (
        PromptMessage(
            role="system",
            content="Persona core:\n" + persona.core.model_dump_json(exclude_none=True),
        ),
        PromptMessage(
            role="system",
            content="Identity:\n" + identity.details.model_dump_json(exclude_none=True),
        ),
        PromptMessage(
            role="system",
            content="Relationship intent and user boundaries:\n"
            + storyline.relationship.model_dump_json(include={"intent", "boundaries"}),
        ),
        PromptMessage(
            role="system",
            content="Current relationship projection:\n"
            + _relationship_json(storyline, relationship),
        ),
        PromptMessage(
            role="system",
            content="Current persona adaptations:\n" + _adaptation_json(adaptations),
        ),
    )
    scene_blocks = (
        PromptMessage(role="system", content="Scene setup:\n" + scene.details.setup),
        PromptMessage(
            role="system",
            content=(
                "Response style:\n"
                + response_style.instruction
                + "\nPreserve the authored relationship boundaries and do not invent shared history."
            ),
        ),
    )
    summary_block = (
        (PromptMessage(role="system", content="Conversation summary:\n" + summary),)
        if summary is not None
        else ()
    )
    history = tuple(
        PromptMessage(
            role="user" if message.role == "user" else "assistant",
            content=message.content,
        )
        for message in messages
    )
    tail = (
        (PromptMessage(role="user", content=current_input),)
        if current_input is not None
        else ()
    )
    return (
        ownership_blocks
        + assemble_continuity_memory_blocks(memories)
        + scene_blocks
        + summary_block
        + history
        + tail
    )


# Transitional import name removed by Slice 7.
assemble_storyline_memory_blocks = assemble_continuity_memory_blocks


def _relationship_json(
    storyline: Storyline, relationship: RelationshipProjection | None
) -> str:
    """Render only qualitative current relationship values.

    Args:
        storyline:
            Owned starting state used before the first evolution effect.
        relationship:
            Persisted current projection when available.

    Returns:
        Compact JSON without ownership, revision, or experiment metadata.
    """

    if relationship is None:
        return storyline.relationship.model_dump_json(
            include={"social", "romantic", "dynamic", "trust", "affection"}
        )

    return relationship.model_dump_json(
        include={"social", "romantic", "dynamic", "trust", "affection", "milestones"}
    )


def _adaptation_json(adaptations: PersonaAdaptationProjection | None) -> str:
    """Render bounded active adaptations without persistence metadata.

    Args:
        adaptations:
            Persisted current adaptations when available.

    Returns:
        Compact JSON containing only typed facets and concise values.
    """

    if adaptations is None:
        return '{"adaptations":[]}'

    return adaptations.model_dump_json(include={"adaptations"})
