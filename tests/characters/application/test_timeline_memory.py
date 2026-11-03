"""Branch- and day-position-aware Timeline memory tests."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

from chat_buddy.characters.application import (
    BaselineTimelineMemoryContextSelector,
    TimelineMemoryEligibility,
    TimelineMemoryExtractionService,
)
from chat_buddy.characters.domain import (
    CompletedTurn,
    ContinuityMode,
    ConversationScope,
    ConversationTarget,
    DayPosition,
    ExtractionBudget,
    ExtractionEffect,
    ExtractionEffectState,
    ExtractionProvenance,
    GenerationConfiguration,
    MemoryAuthorship,
    MemoryDelta,
    MemoryEvidence,
    MemoryExtractionContext,
    MemoryRevision,
    MemoryRevisionKind,
    MemoryRevisionState,
    Message,
    NoMemoryChangeCommand,
    PromptMessage,
    StartingRelationship,
    StorylineMemory,
    StrategyIdentity,
)

NOW = datetime(2026, 11, 3, tzinfo=UTC)


class _WordCounter:
    """Count whitespace-delimited prompt words deterministically."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Count every whitespace-delimited word.

        Args:
            messages:
                Complete rendered prompt messages.

        Returns:
            Deterministic approximate token count.
        """

        return sum(len(message.content.split()) for message in messages)


def _scope() -> ConversationScope:
    """Create complete Timeline conversation ownership.

    Returns:
        Isolated conversation scope.
    """

    return ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )


def _turn(scope: ConversationScope, sequence: int) -> CompletedTurn:
    """Create one complete Timeline turn.

    Args:
        scope:
            Complete conversation ownership.
        sequence:
            Odd user-message sequence.

    Returns:
        Adjacent complete turn.
    """

    user = Message(
        id=uuid4(),
        scope=scope,
        sequence=sequence,
        role="user",
        content="I prefer tea.",
        created_at=NOW,
    )
    persona = Message(
        id=uuid4(),
        scope=scope,
        sequence=sequence + 1,
        role="persona",
        content="I'll remember that.",
        created_at=NOW,
    )
    return CompletedTurn(user=user, persona=persona)


def _provenance() -> ExtractionProvenance:
    """Create stable extraction provenance.

    Returns:
        Valid extraction provenance.
    """

    return ExtractionProvenance(
        selector=StrategyIdentity(name="test.selector", version="1.0.0"),
        extractor=StrategyIdentity(name="test.extractor", version="1.0.0"),
        prompt_schema_version="1.0.0",
        provider="test",
        model="memory",
        configuration=GenerationConfiguration(),
    )


def _memory(
    scope: ConversationScope,
    turn: CompletedTurn,
    *,
    occurrence: int,
    learned: int,
    active: bool = True,
) -> StorylineMemory:
    """Create one Timeline-owned logical memory.

    Args:
        scope:
            Evidence ownership.
        turn:
            Supporting selected turn.
        occurrence:
            Occurrence day position.
        learned:
            Learned day position.
        active:
            Whether the current revision is prompt eligible.

    Returns:
        Complete one-revision logical memory.
    """

    memory_id = uuid4()
    day_id = uuid4()
    evidence = MemoryEvidence(
        id=uuid4(),
        scope=scope,
        day_id=day_id,
        user_message_id=turn.user.id,
        persona_message_id=turn.persona.id,
        persona_checkpoint=turn.persona.sequence,
        occurrence=DayPosition(day_id=uuid4(), position=occurrence),
        learned=DayPosition(day_id=day_id, position=learned),
        extraction=_provenance(),
        created_at=NOW,
    )
    first = MemoryRevision(
        id=uuid4(),
        memory_id=memory_id,
        continuity_id=scope.continuity_id,
        revision=1,
        predecessor_id=None,
        subject="preferred drink",
        content="The identity prefers tea.",
        state=(
            MemoryRevisionState.ACTIVE if active else MemoryRevisionState.SUPERSEDED
        ),
        authorship=MemoryAuthorship.EXTRACTED,
        kind=MemoryRevisionKind.EXTRACTION,
        source=evidence,
        created_at=NOW,
    )
    revision = first
    revisions: tuple[MemoryRevision, ...] = (first,)
    if not active:
        revision = MemoryRevision(
            id=uuid4(),
            memory_id=memory_id,
            continuity_id=scope.continuity_id,
            revision=2,
            predecessor_id=first.id,
            subject=first.subject,
            content=first.content,
            state=MemoryRevisionState.EXCLUDED,
            authorship=first.authorship,
            kind=MemoryRevisionKind.EXCLUSION,
            source=evidence,
            created_at=NOW,
        )
        revisions = (first, revision)
    return StorylineMemory(
        id=memory_id,
        continuity_id=scope.continuity_id,
        current_revision_id=revision.id,
        revisions=revisions,
        evidence=(evidence,),
    )


def test_timeline_eligibility_requires_selected_past_day_evidence() -> None:
    """Exclude future, deselected, inactive, and foreign Timeline memory."""

    scope = _scope()
    selected_turn = _turn(scope, 1)
    deselected_turn = _turn(scope, 3)
    eligible = _memory(scope, selected_turn, occurrence=1, learned=2)
    future = _memory(scope, selected_turn, occurrence=2, learned=3)
    deselected = _memory(scope, deselected_turn, occurrence=1, learned=1)
    inactive = _memory(scope, selected_turn, occurrence=1, learned=1, active=False)
    foreign_scope = _scope()
    foreign_turn = _turn(foreign_scope, 1)
    foreign = _memory(foreign_scope, foreign_turn, occurrence=1, learned=1)

    result = TimelineMemoryEligibility().select(
        (eligible, future, deselected, inactive, foreign),
        scope.continuity_id,
        DayPosition(day_id=uuid4(), position=2),
        frozenset({selected_turn.persona.id}),
    )

    assert result == (eligible,)


def test_timeline_extraction_selection_uses_day_and_current_day_history() -> None:
    """Render Timeline memory without inventing a Storyline scene block."""

    scope = _scope()
    recent = _turn(scope, 1)
    source = _turn(scope, 3)
    memory = _memory(scope, recent, occurrence=1, learned=1)
    context = MemoryExtractionContext(
        scope=scope,
        day=DayPosition(day_id=uuid4(), position=2),
        identity_label="You",
        persona_label="Companion",
        starting_relationship=StartingRelationship.model_construct(),
        summary=None,
        recent_turns=(recent,),
        eligible_memories=(memory,),
        source_turn=source,
    )

    selection = BaselineTimelineMemoryContextSelector(_WordCounter()).select(
        context,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=8),
    )

    assert selection.included_turn_ids == (recent.persona.id,)
    assert selection.selector.name == "baseline.timeline_memory_context"
    assert selection.included_memory_ids == (memory.id,)
    assert all("[scene setup]" not in block for block in selection.prompt)
    assert selection.prompt[-1].startswith(f"[new evidence:{source.persona.id}]")


def test_timeline_extraction_reserves_one_effect_for_the_source_turn() -> None:
    """Use the Timeline reservation seam and return its terminal effect."""

    scope = _scope()
    day_id = uuid4()
    source_id = uuid4()
    target = ConversationTarget(
        scope=scope, mode=ContinuityMode.TIMELINE, day_id=day_id
    )
    provenance = _provenance()
    selection = Mock()
    selection.id = uuid4()
    selection.selector = provenance.selector
    selection.context.scope = scope
    selection.context.source_turn.persona.id = source_id
    delta = MemoryDelta(
        selection_id=selection.id,
        scope=scope,
        source_persona_message_id=source_id,
        extractor=provenance.extractor,
        commands=(NoMemoryChangeCommand(),),
    )
    reserved = ExtractionEffect(
        id=uuid4(),
        scope=scope,
        day_id=day_id,
        source_persona_message_id=source_id,
        state=ExtractionEffectState.RESERVED,
        provenance=None,
        created_at=NOW,
        completed_at=None,
    )
    terminal = reserved.model_copy(
        update={
            "state": ExtractionEffectState.NO_CHANGE,
            "provenance": provenance,
            "completed_at": NOW,
        }
    )
    contexts = Mock()
    contexts.build.return_value = selection
    extractor = Mock()
    extractor.strategy_id = provenance.extractor
    extractor.extract.return_value = delta
    extractor.provenance.return_value = provenance
    memories = Mock()
    memories.list.return_value = ()
    effects = Mock()
    effects.reserve_timeline.return_value = reserved
    effects.apply.return_value = terminal
    service = TimelineMemoryExtractionService(
        contexts,
        extractor,
        memories,
        effects,
        ExtractionBudget(input_tokens=512, fixed_overhead_tokens=8),
    )

    result = service.process(target, source_id)

    assert result == terminal
    effects.reserve_timeline.assert_called_once_with(scope, day_id, source_id)
    selection.validate_delta.assert_called_once_with(delta)
    effects.apply.assert_called_once_with(reserved.id, delta, provenance)
