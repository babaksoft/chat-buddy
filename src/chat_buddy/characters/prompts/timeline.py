"""Fixed current-day Timeline response prompt blocks."""

from chat_buddy.characters.domain import (
    Identity,
    Message,
    Persona,
    PromptMessage,
    ResponseStyle,
    Timeline,
)


def assemble_timeline_prompt(
    persona: Persona,
    identity: Identity,
    timeline: Timeline,
    response_style: ResponseStyle,
    messages: tuple[Message, ...],
    current_input: str | None = None,
    summary: str | None = None,
) -> tuple[PromptMessage, ...]:
    """Render required Timeline start facts and current-day transcript only.

    Args:
        persona:
            Frozen authored persona core.
        identity:
            Frozen authored identity.
        timeline:
            Owned starting relationship and lifecycle snapshot.
        response_style:
            Effective presentation snapshot reserved for this response.
        messages:
            Selected complete turns from the target day only.
        current_input:
            New input, absent when continuing an existing tail.
        summary:
            Compatible summary from the target day only.

    Returns:
        Ordered provider input without other-day or derived-state context.
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
            content="Relationship intent and user boundaries:\n"
            + timeline.relationship.model_dump_json(include={"intent", "boundaries"}),
        ),
        PromptMessage(
            role="system",
            content="Starting relationship state:\n"
            + timeline.relationship.model_dump_json(
                include={"social", "romantic", "dynamic", "trust", "affection"}
            ),
        ),
        PromptMessage(
            role="system",
            content="Response style:\n"
            + response_style.instruction
            + "\nPreserve the authored identity and relationship boundaries and "
            "do not invent shared history.",
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
