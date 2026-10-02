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
    summary: str | None = None,
) -> tuple[PromptMessage, ...]:
    """Render mandatory blocks, summary, selected history, and current input.

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
        summary:
            Active conversation summary covering messages before this history.

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


def assemble_summary_prompt(
    prior_summary: str | None, turns: tuple[tuple[str, str], ...]
) -> tuple[PromptMessage, ...]:
    """Render one bounded rolling-summary request.

    Args:
        prior_summary:
            Existing summary content when advancing a lineage.
        turns:
            Newly covered user/persona text pairs in chronological order.

    Returns:
        Provider-neutral summary prompt with no response-context policy.
    """

    instruction = PromptMessage(
        role="system",
        content=(
            "Update the conversation summary from the supplied prior summary and "
            "new complete turns. Preserve relevant facts, relationship context, "
            "open threads, and character consistency. Do not invent events. "
            "Return only a concise plain-text summary."
        ),
    )
    prior = (
        (PromptMessage(role="system", content="Prior summary:\n" + prior_summary),)
        if prior_summary is not None
        else ()
    )
    additions = tuple(
        PromptMessage(
            role="user",
            content=f"Complete turn {index}:\nUser: {user}\nPersona: {persona}",
        )
        for index, (user, persona) in enumerate(turns, start=1)
    )
    return (instruction,) + prior + additions
