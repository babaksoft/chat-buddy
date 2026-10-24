"""Contextual Storyline memory selection and delta contract tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    CompletedTurn,
    ConversationScope,
    CreateMemoryCommand,
    ExtractionBudget,
    ExtractionProvenance,
    GenerationConfiguration,
    InvalidMemoryDeltaTargetError,
    MemoryAuthorship,
    MemoryDelta,
    MemoryEvidence,
    MemoryExtractionContext,
    MemoryRevision,
    MemoryRevisionKind,
    MemoryRevisionState,
    MemorySelectionResult,
    Message,
    NoMemoryChangeCommand,
    ProtectedMemoryCorrectionError,
    RecordMemoryConflictCommand,
    ReinforceMemoryCommand,
    RelationshipIntent,
    ScenePosition,
    StartingOrigins,
    StartingRelationship,
    StorylineMemory,
    StrategyIdentity,
    SupersedeMemoryCommand,
)

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def _strategy(name: str) -> StrategyIdentity:
    """Create a stable strategy identity.

    Args:
        name:
            Machine-readable strategy name.

    Returns:
        Versioned strategy identity.
    """

    return StrategyIdentity(name=name, version="1.0.0")


def _turn(scope: ConversationScope, sequence: int) -> CompletedTurn:
    """Create one complete scoped selected turn.

    Args:
        scope:
            Complete conversation ownership.
        sequence:
            Odd user-message sequence.

    Returns:
        Complete adjacent turn.
    """

    return CompletedTurn(
        user=Message(
            id=uuid4(),
            scope=scope,
            sequence=sequence,
            role="user",
            content="I always order tea.",
            created_at=NOW,
        ),
        persona=Message(
            id=uuid4(),
            scope=scope,
            sequence=sequence + 1,
            role="persona",
            content="I'll remember that.",
            created_at=NOW,
        ),
    )


def _relationship() -> StartingRelationship:
    """Create the continuity starting relationship.

    Returns:
        Valid immutable relationship.
    """

    return StartingRelationship(
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


def _context(
    *, authorship: MemoryAuthorship = MemoryAuthorship.EXTRACTED
) -> MemoryExtractionContext:
    """Create one context with history, eligible memory, and new evidence.

    Args:
        authorship:
            Current memory content authority.

    Returns:
        Valid extraction context.
    """

    scope = ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )
    scene = ScenePosition(scene_id=uuid4(), position=2)
    prior_turn, source_turn = _turn(scope, 1), _turn(scope, 3)
    provenance = ExtractionProvenance(
        selector=_strategy("baseline.context"),
        extractor=_strategy("baseline.delta"),
        prompt_schema_version="1.0.0",
        provider="ollama",
        model="local-model",
        configuration=GenerationConfiguration(max_output_tokens=256),
    )
    evidence = MemoryEvidence(
        id=uuid4(),
        scope=scope,
        scene_id=scene.scene_id,
        user_message_id=prior_turn.user.id,
        persona_message_id=prior_turn.persona.id,
        persona_checkpoint=2,
        occurrence=ScenePosition(scene_id=uuid4(), position=1),
        learned=scene,
        extraction=provenance,
        created_at=NOW,
    )
    memory_id = uuid4()
    extracted = MemoryRevision(
        id=uuid4(),
        memory_id=memory_id,
        continuity_id=scope.continuity_id,
        revision=1,
        predecessor_id=None,
        subject="favorite drink",
        content="The user's favorite drink is tea.",
        state=(
            MemoryRevisionState.SUPERSEDED
            if authorship == MemoryAuthorship.USER
            else MemoryRevisionState.ACTIVE
        ),
        authorship=MemoryAuthorship.EXTRACTED,
        kind=MemoryRevisionKind.EXTRACTION,
        source=evidence,
        created_at=NOW,
    )
    revisions: tuple[MemoryRevision, ...]
    if authorship == MemoryAuthorship.USER:
        current = MemoryRevision(
            id=uuid4(),
            memory_id=memory_id,
            continuity_id=scope.continuity_id,
            revision=2,
            predecessor_id=extracted.id,
            subject=extracted.subject,
            content=extracted.content,
            state=MemoryRevisionState.ACTIVE,
            authorship=MemoryAuthorship.USER,
            kind=MemoryRevisionKind.USER_CORRECTION,
            source=evidence,
            created_at=NOW,
        )
        revisions = (extracted, current)
    else:
        current = extracted
        revisions = (extracted,)
    memory = StorylineMemory(
        id=memory_id,
        continuity_id=scope.continuity_id,
        current_revision_id=current.id,
        revisions=revisions,
        evidence=(evidence,),
    )
    return MemoryExtractionContext(
        scope=scope,
        scene=scene,
        identity_label="You",
        persona_label="Guide",
        starting_relationship=_relationship(),
        scene_setup="At a quiet cafe.",
        summary=None,
        recent_turns=(prior_turn,),
        eligible_memories=(memory,),
        source_turn=source_turn,
    )


def _selection(context: MemoryExtractionContext) -> MemorySelectionResult:
    """Select every optional record in a valid bounded snapshot.

    Args:
        context:
            Eligible extraction context.

    Returns:
        Valid selection result.
    """

    return MemorySelectionResult(
        id=uuid4(),
        selector=_strategy("baseline.context"),
        context=context,
        included_turn_ids=tuple(turn.persona.id for turn in context.recent_turns),
        omitted_turn_ids=(),
        included_memory_ids=tuple(memory.id for memory in context.eligible_memories),
        omitted_memory_ids=(),
        summary_included=False,
        prompt=("identity: You", "new evidence: I always order tea."),
        token_count=32,
        budget=ExtractionBudget(input_tokens=256, fixed_overhead_tokens=16),
    )


def _source_evidence(context: MemoryExtractionContext) -> MemoryEvidence:
    """Create evidence that cites the exact context source turn.

    Args:
        context:
            Source extraction context.

    Returns:
        Valid exact-turn evidence.
    """

    return MemoryEvidence(
        id=uuid4(),
        scope=context.scope,
        scene_id=context.scene.scene_id,
        user_message_id=context.source_turn.user.id,
        persona_message_id=context.source_turn.persona.id,
        persona_checkpoint=context.source_turn.persona.sequence,
        occurrence=context.scene,
        learned=context.scene,
        extraction=context.eligible_memories[0].current.source.extraction,
        created_at=NOW,
    )


def _delta(
    selection: MemorySelectionResult, commands: tuple[object, ...]
) -> MemoryDelta:
    """Build a delta over a selection.

    Args:
        selection:
            Source context selection.
        operations:
            Typed operation values.

    Returns:
        Validated structured delta.
    """

    return MemoryDelta.model_validate(
        {
            "selection_id": selection.id,
            "scope": selection.context.scope,
            "source_persona_message_id": selection.context.source_turn.persona.id,
            "extractor": _strategy("baseline.delta"),
            "commands": commands,
        }
    )


def test_context_rejects_foreign_turns_and_future_or_excluded_memory() -> None:
    """Keep the immutable extraction snapshot owned, active, and time eligible."""

    context = _context()
    foreign_scope = context.scope.model_copy(update={"continuity_id": uuid4()})
    with pytest.raises(ValidationError, match="source scope"):
        MemoryExtractionContext.model_validate(
            {
                **context.model_dump(),
                "source_turn": _turn(foreign_scope, 3),
            }
        )

    memory = context.eligible_memories[0]
    extracted = memory.current.model_copy(
        update={"state": MemoryRevisionState.SUPERSEDED}
    )
    excluded_revision = MemoryRevision(
        id=uuid4(),
        memory_id=memory.id,
        continuity_id=memory.continuity_id,
        revision=2,
        predecessor_id=extracted.id,
        subject=extracted.subject,
        content=extracted.content,
        state=MemoryRevisionState.EXCLUDED,
        authorship=extracted.authorship,
        kind=MemoryRevisionKind.EXCLUSION,
        source=extracted.source,
        created_at=NOW,
    )
    excluded = StorylineMemory(
        id=memory.id,
        continuity_id=memory.continuity_id,
        current_revision_id=excluded_revision.id,
        revisions=(extracted, excluded_revision),
        evidence=memory.evidence,
    )
    with pytest.raises(ValidationError, match="ineligible memory"):
        MemoryExtractionContext.model_validate(
            {**context.model_dump(), "eligible_memories": (excluded,)}
        )


def test_selection_requires_exact_partitions_and_positive_bounded_budget() -> None:
    """Reject invented identifiers, exhausted capacity, and token overflow."""

    context = _context()
    selection = _selection(context)
    assert selection.included_memory_ids == (context.eligible_memories[0].id,)
    with pytest.raises(ValidationError, match="partition context"):
        MemorySelectionResult.model_validate(
            {**selection.model_dump(), "included_memory_ids": (uuid4(),)}
        )
    with pytest.raises(ValidationError, match="exceeds"):
        MemorySelectionResult.model_validate(
            {**selection.model_dump(), "token_count": 257}
        )
    with pytest.raises(ValidationError, match="positive context capacity"):
        ExtractionBudget(input_tokens=16, fixed_overhead_tokens=16)


def test_delta_accepts_every_operation_and_no_change_alone() -> None:
    """Represent create, reinforce, supersede, conflict, and no-change results."""

    context = _context()
    selection = _selection(context)
    evidence = _source_evidence(context)
    target = context.eligible_memories[0]
    commands = (
        CreateMemoryCommand(
            subject="usual order",
            content="The user usually orders tea.",
            occurrence=context.scene,
            evidence=evidence,
        ),
        ReinforceMemoryCommand(
            target_memory_id=target.id,
            expected_revision_id=target.current.id,
            content=target.current.content,
            evidence=evidence,
        ),
        RecordMemoryConflictCommand(
            target_memory_id=None,
            expected_revision_id=None,
            subject="cafe preference",
            content="The user might dislike busy cafes.",
            occurrence=context.scene,
            evidence=evidence,
        ),
    )
    delta = _delta(selection, commands)
    assert tuple(command.operation for command in delta.commands) == (
        "create",
        "reinforce",
        "conflict",
    )
    assert "kind" not in delta.commands[0].model_dump()
    assert delta.commands[0].model_dump()["operation"] == "create"
    assert _delta(selection, (NoMemoryChangeCommand(),)).commands[0].operation == (
        "no_change"
    )


def test_delta_rejects_contradictory_targets_subjects_and_mixed_no_change() -> None:
    """Reject operation sets that cannot be applied atomically."""

    context = _context()
    selection = _selection(context)
    evidence = _source_evidence(context)
    target = context.eligible_memories[0]
    reinforce = ReinforceMemoryCommand(
        target_memory_id=target.id,
        expected_revision_id=target.current.id,
        content=target.current.content,
        evidence=evidence,
    )
    supersede = SupersedeMemoryCommand(
        target_memory_id=target.id,
        expected_revision_id=target.current.id,
        subject="favorite drink",
        content="The user's favorite drink is coffee.",
        occurrence=context.scene,
        evidence=evidence,
    )
    with pytest.raises(ValidationError, match="twice"):
        _delta(selection, (reinforce, supersede))
    with pytest.raises(ValidationError, match="only delta command"):
        _delta(selection, (NoMemoryChangeCommand(), reinforce))

    first = CreateMemoryCommand(
        subject="Usual Order",
        content="The user orders tea.",
        occurrence=context.scene,
        evidence=evidence,
    )
    second = CreateMemoryCommand(
        subject="usual order",
        content="The user orders coffee.",
        occurrence=context.scene,
        evidence=evidence,
    )
    with pytest.raises(ValidationError, match="competing normalized subjects"):
        _delta(selection, (first, second))


def test_selection_blocks_omitted_stale_and_user_protected_targets() -> None:
    """Keep extraction within supplied opaque targets and user authority."""

    protected_context = _context(authorship=MemoryAuthorship.USER)
    selection = _selection(protected_context)
    evidence = _source_evidence(protected_context)
    target = protected_context.eligible_memories[0]
    supersede = SupersedeMemoryCommand(
        target_memory_id=target.id,
        expected_revision_id=target.current.id,
        subject="favorite drink",
        content="The user's favorite drink is coffee.",
        occurrence=protected_context.scene,
        evidence=evidence,
    )
    delta = _delta(selection, (supersede,))
    with pytest.raises(ProtectedMemoryCorrectionError):
        selection.validate_delta(delta)

    omitted = selection.model_copy(
        update={
            "included_memory_ids": (),
            "omitted_memory_ids": (target.id,),
        }
    )
    with pytest.raises(InvalidMemoryDeltaTargetError):
        omitted.validate_delta(delta)
