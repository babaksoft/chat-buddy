"""Fixed current-day Timeline response prompt blocks."""

from chat_buddy.characters.domain import (
    ContinuityMemory,
    Identity,
    Message,
    Persona,
    PersonaAdaptationProjection,
    PromptMessage,
    RelationshipProjection,
    ResponseStyle,
    Timeline,
    TimelineDay,
)
from chat_buddy.characters.prompts.storyline import (
    assemble_continuity_memory_blocks,
)

TIMELINE_RESPONSE_PROMPT_SCHEMA_VERSION = "1.0.0"


def assemble_timeline_prompt(
    persona: Persona,
    identity: Identity,
    timeline: Timeline,
    day: TimelineDay,
    response_style: ResponseStyle,
    messages: tuple[Message, ...],
    current_input: str | None = None,
    summary: str | None = None,
    memories: tuple[ContinuityMemory, ...] = (),
    relationship: RelationshipProjection | None = None,
    adaptations: PersonaAdaptationProjection | None = None,
) -> tuple[PromptMessage, ...]:
    """Render derived continuity and the exact current-day transcript.

    Args:
        persona:
            Frozen authored persona core.
        identity:
            Frozen authored identity.
        timeline:
            Owned starting relationship and lifecycle snapshot.
        day:
            Exact represented day owning the conversation.
        response_style:
            Effective presentation snapshot reserved for this response.
        messages:
            Selected complete turns from the target day only.
        current_input:
            New input, absent when continuing an existing tail.
        summary:
            Compatible summary from the target day only.
        memories:
            Selected eligible Timeline memories in response-strategy order.
        relationship:
            Current qualitative relationship projection when initialized.
        adaptations:
            Current continuity-local persona adaptations when initialized.

    Returns:
        Ordered provider input without other-day or derived-state context.
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
            + timeline.relationship.model_dump_json(include={"intent", "boundaries"}),
        ),
        PromptMessage(
            role="system",
            content="Current relationship projection:\n"
            + _relationship_json(timeline, relationship),
        ),
        PromptMessage(
            role="system",
            content="Current persona adaptations:\n" + _adaptation_json(adaptations),
        ),
    )
    day_blocks = (
        PromptMessage(
            role="system",
            content=(
                "Current-day state:\n"
                f"Local date: {day.boundary.local_date.isoformat()}\n"
                f"Calendar timezone: {day.boundary.timezone}\n\n"
                "Response style:\n"
                + response_style.instruction
                + "\nPreserve the authored identity and relationship boundaries and "
                "do not invent shared history."
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
        + day_blocks
        + summary_block
        + history
        + tail
    )


def _relationship_json(
    timeline: Timeline, relationship: RelationshipProjection | None
) -> str:
    """Render current qualitative relationship values without metadata.

    Args:
        timeline:
            Owned starting state used before the first evolution effect.
        relationship:
            Persisted current projection when available.

    Returns:
        Compact qualitative relationship JSON.
    """

    if relationship is None:
        return timeline.relationship.model_dump_json(
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
        Compact adaptations JSON.
    """

    if adaptations is None:
        return '{"adaptations":[]}'

    return adaptations.model_dump_json(include={"adaptations"})
