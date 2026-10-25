"""Fixed Storyline response prompt blocks."""

from chat_buddy.characters.domain import (
    Identity,
    Message,
    Persona,
    PromptMessage,
    Scene,
    Storyline,
)


def assemble_storyline_prompt(
    persona: Persona,
    identity: Identity,
    storyline: Storyline,
    scene: Scene,
    messages: tuple[Message, ...],
    current_input: str | None = None,
    summary: str | None = None,
) -> tuple[PromptMessage, ...]:
    """Render one scene without titles, other scenes, or future memory blocks.

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

    Returns:
        Ordered provider input without memory placeholders or partial output.
    """

    blocks = (
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
    return blocks + summary_block + history + tail
