"""Fixed Storyline response prompt blocks."""

from chat_buddy.characters.domain import (
    Identity,
    Message,
    Persona,
    PromptMessage,
    Scene,
    Storyline,
    StorylineMemory,
)


def assemble_storyline_memory_blocks(
    memories: tuple[StorylineMemory, ...],
) -> tuple[PromptMessage, ...]:
    """Render complete eligible memories as indivisible prompt blocks.

    Args:
        memories:
            Ordered selected Storyline memories.

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
    messages: tuple[Message, ...],
    current_input: str | None = None,
    summary: str | None = None,
    memories: tuple[StorylineMemory, ...] = (),
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
            Exact scene setup and fixed response-style snapshot.
        messages:
            Selected complete turns from this scene only.
        current_input:
            New input, absent when continuing an existing tail.
        summary:
            Compatible summary from this scene only.
        memories:
            Selected eligible continuity memories in response-strategy order.

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
            content="Relationship intent and starting state:\n"
            + storyline.relationship.model_dump_json()
            + "\nThese are starting qualities, not evidence of shared events. Do not invent shared history.",
        ),
    )
    scene_blocks = (
        PromptMessage(role="system", content="Scene setup:\n" + scene.details.setup),
        PromptMessage(
            role="system",
            content="Response style:\n" + scene.details.response_style.instruction,
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
        + assemble_storyline_memory_blocks(memories)
        + scene_blocks
        + summary_block
        + history
        + tail
    )
