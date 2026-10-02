"""Fixed Ongoing prompt blocks."""

from chat_buddy.characters.domain import (
    Continuity,
    Identity,
    Message,
    Persona,
    PromptMessage,
)

# Extra deterministic safety reserve beyond the provider counter's framing.
PROMPT_OVERHEAD_TOKENS = 64


def assemble_ongoing_prompt(
    persona: Persona,
    identity: Identity,
    continuity: Continuity,
    messages: tuple[Message, ...],
    current_input: str | None = None,
) -> tuple[PromptMessage, ...]:
    """Render mandatory blocks followed by full committed history and new input.

    Args:
        persona:
            Frozen authored persona core.
        identity:
            Frozen authored identity.
        continuity:
            Owned intent and starting state; no inferred evolution.
        messages:
            Committed complete turns and at most one unmatched user tail.
        current_input:
            New input, absent when continuing an existing tail.

    Returns:
        Ordered provider input without partial output or memory.
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
            + continuity.relationship.model_dump_json()
            + "\nThese are starting qualities, not evidence of shared events. Do not invent shared history.",
        ),
        PromptMessage(
            role="system",
            content="Respond as the persona in a natural conversation. Use clear text and preserve the authored identity and relationship boundaries.",
        ),
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
    return blocks + history + tail
