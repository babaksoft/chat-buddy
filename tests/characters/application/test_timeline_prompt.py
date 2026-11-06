"""Deterministic Timeline response-context assembly."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from chat_buddy.characters.application import TimelineContextBudgeter
from chat_buddy.characters.domain import (
    AdaptationFacet,
    ApplicationLocalTimezone,
    CompletedTurn,
    ContextCapacityError,
    ContinuityEntry,
    ContinuityLifecycle,
    ContinuityMemory,
    ContinuityMode,
    ConversationScope,
    DayBoundary,
    EffectiveGeneration,
    EligibleContext,
    EvolutionScope,
    GenerationConfiguration,
    Identity,
    IdentityDetails,
    MemoryRevision,
    Message,
    ModelDescriptor,
    Persona,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    PersonaCore,
    PromptMessage,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipIntent,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    ResponseStyle,
    StartingOrigins,
    StartingRelationship,
    Timeline,
    TimelineDay,
)
from chat_buddy.characters.prompts import assemble_timeline_prompt


class MessageCounter:
    """Count each complete provider message as one token."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Return the number of indivisible provider messages.

        Args:
            messages:
                Complete prompt candidate.

        Returns:
            Number of messages.
        """

        return len(messages)


def test_timeline_prompt_orders_long_term_state_before_current_day_context() -> None:
    """Render derived state, memory, and only the exact current-day transcript."""

    persona, identity, timeline, day = _owned_values()
    messages = _turn(day.scope, "Today’s question 🌙", "Today’s answer ✨")
    memory = _memory(timeline.id, "Prior day", "They agreed to meet today.")
    projections = _projections(timeline)

    prompt = assemble_timeline_prompt(
        persona,
        identity,
        timeline,
        day,
        _style(),
        messages,
        current_input="What happens next?",
        summary="They greeted each other today.",
        memories=(memory,),
        relationship=projections[0],
        adaptations=projections[1],
    )

    rendered = "\n".join(message.content for message in prompt)
    headings = (
        "Persona core:",
        "Identity:",
        "Relationship intent and user boundaries:",
        "Current relationship projection:",
        "Current persona adaptations:",
        "Continuity memory:",
        "Current-day state:",
        "Response style:",
        "Conversation summary:",
        "Today’s question 🌙",
        "Today’s answer ✨",
        "What happens next?",
    )
    positions = tuple(rendered.index(value) for value in headings)
    assert positions == tuple(sorted(positions))
    assert "They agreed to meet today." in rendered
    assert '"social":"close_friend"' in rendered
    assert "Use candid warmth." in rendered
    assert '"revision"' not in rendered
    assert "Hidden Timeline title" not in rendered
    assert "other-day transcript" not in rendered
    assert [message.role for message in prompt[-3:]] == [
        "user",
        "assistant",
        "user",
    ]


def test_timeline_budget_selects_whole_optional_records_under_provider_limit() -> None:
    """Keep mandatory input and deterministic first memory without partial records."""

    persona, identity, timeline, day = _owned_values()
    first = _memory(timeline.id, "Alpha", "First complete fact.")
    second = _memory(timeline.id, "Beta", "Second complete fact.")
    turn = _turn(day.scope, "Earlier user", "Earlier persona")
    context = EligibleContext(
        summary=None,
        uncovered_turns=(CompletedTurn(user=turn[0], persona=turn[1]),),
        current_input="Current input",
    )

    selection = TimelineContextBudgeter().assemble(
        persona,
        identity,
        timeline,
        day,
        _style(),
        context,
        _generation(72),
        MessageCounter(),
        (first, second),
    )

    rendered = "\n".join(message.content for message in selection.prompt)
    assert "First complete fact." in rendered
    assert "Second complete fact." not in rendered
    assert "Earlier user" not in rendered
    assert selection.included_turns == ()
    assert selection.omitted_turns == (CompletedTurn(user=turn[0], persona=turn[1]),)
    assert selection.tokens + 64 <= 72

    with pytest.raises(ContextCapacityError, match="Mandatory Timeline"):
        TimelineContextBudgeter().assemble(
            persona,
            identity,
            timeline,
            day,
            _style(),
            context.model_copy(update={"uncovered_turns": ()}),
            _generation(70),
            MessageCounter(),
        )


def _owned_values() -> tuple[Persona, Identity, Timeline, TimelineDay]:
    """Create one fully owned Timeline day.

    Returns:
        Persona, identity, Timeline, and represented day.
    """

    identity = Identity(
        id=uuid4(),
        details=IdentityDetails(name="Traveler"),
        is_default=False,
        is_frozen=True,
        revision=1,
    )
    persona = Persona(
        id=uuid4(),
        core=PersonaCore(name="Mina", definition="A thoughtful old friend."),
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
    timeline = Timeline(
        id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        name="Hidden Timeline title",
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=relationship,
        calendar_timezone=ApplicationLocalTimezone(name="Asia/Tehran"),
        revision=1,
    )
    entry = ContinuityEntry(
        id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        continuity_id=timeline.id,
        conversation_id=uuid4(),
        mode=ContinuityMode.TIMELINE,
        position=2,
    )
    day = TimelineDay(
        entry=entry,
        boundary=DayBoundary(
            local_date=date(2026, 11, 2),
            timezone="Asia/Tehran",
            opens_at=datetime(2026, 11, 1, 20, 30, tzinfo=UTC),
            closes_at=datetime(2026, 11, 2, 20, 30, tzinfo=UTC),
        ),
    )
    return persona, identity, timeline, day


def _turn(scope: ConversationScope, user: str, persona: str) -> tuple[Message, Message]:
    """Create one complete selected current-day turn.

    Args:
        scope:
            Exact day conversation ownership.
        user:
            User content.
        persona:
            Persona content.

    Returns:
        Adjacent user and persona messages.
    """

    now = datetime(2026, 11, 2, 8, tzinfo=UTC)
    return (
        Message(
            id=uuid4(),
            scope=scope,
            sequence=1,
            role="user",
            content=user,
            created_at=now,
        ),
        Message(
            id=uuid4(),
            scope=scope,
            sequence=2,
            role="persona",
            content=persona,
            created_at=now,
        ),
    )


def _memory(continuity_id: UUID, subject: str, content: str) -> ContinuityMemory:
    """Create one complete current memory revision for rendering.

    Args:
        continuity_id:
            Timeline owner identifier.
        subject:
            Stable memory subject.
        content:
            Current corrected or extracted content.

    Returns:
        Minimal immutable memory aggregate.
    """

    return ContinuityMemory.model_construct(
        id=uuid4(),
        continuity_id=continuity_id,
        current_revision_id=uuid4(),
        revisions=(MemoryRevision.model_construct(subject=subject, content=content),),
        evidence=(),
    )


def _projections(
    timeline: Timeline,
) -> tuple[RelationshipProjection, PersonaAdaptationProjection]:
    """Create current relationship and persona-adaptation projections.

    Args:
        timeline:
            Projection owner.

    Returns:
        Current relationship and adaptation values.
    """

    scope = EvolutionScope(
        identity_id=timeline.identity_id,
        persona_id=timeline.persona_id,
        continuity_id=timeline.id,
    )
    return (
        RelationshipProjection(
            scope=scope,
            revision=2,
            social=RelationshipSocialStatus.CLOSE_FRIEND,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.COMFORTABLE,
            trust=RelationshipTrust.TRUSTING,
            affection=RelationshipAffection.WARM,
        ),
        PersonaAdaptationProjection(
            scope=scope,
            revision=2,
            adaptations=(
                PersonaAdaptation(
                    facet=AdaptationFacet.COMMUNICATION_STYLE,
                    value="Use candid warmth.",
                ),
            ),
        ),
    )


def _style() -> ResponseStyle:
    """Return one effective style snapshot.

    Returns:
        Deterministic response style.
    """

    return ResponseStyle(
        name="characters.response_style",
        version="1.0.0",
        instruction="Use balanced scene detail and a concise response.",
    )


def _generation(input_tokens: int) -> EffectiveGeneration:
    """Create a response generation with an exact input capacity.

    Args:
        input_tokens:
            Capacity after output reservation.

    Returns:
        Valid effective generation.
    """

    return EffectiveGeneration(
        model=ModelDescriptor(
            provider="fake",
            model="timeline-context",
            context_tokens=input_tokens + 1,
            output_tokens=1,
            capabilities=frozenset({"response"}),
        ),
        configuration=GenerationConfiguration(max_output_tokens=1),
        capability="response",
        input_tokens=input_tokens,
    )
