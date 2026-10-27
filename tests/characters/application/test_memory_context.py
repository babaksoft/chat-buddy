"""Branch-aware Storyline extraction-context application tests."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from chat_buddy.characters.application import (
    BaselineMemoryContextSelector,
    BaselineResponseMemorySelector,
    StorylineExtractionContextService,
    StorylineMemoryEligibility,
    StorylineResponseMemoryService,
)
from chat_buddy.characters.domain import (
    CompletedTurn,
    ContextCapacityError,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationScope,
    ConversationTarget,
    ExtractionBudget,
    ExtractionProvenance,
    GenerationConfiguration,
    Identity,
    IdentityDetails,
    MemoryAuthorship,
    MemoryEvidence,
    MemoryExtractionContext,
    MemoryRevision,
    MemoryRevisionKind,
    MemoryRevisionState,
    Message,
    MessageNode,
    Persona,
    PersonaCore,
    PromptMessage,
    RelationshipIntent,
    ResponseMemoryBudget,
    ResponseStyleSnapshot,
    Scene,
    SceneDetails,
    ScenePosition,
    SceneSequence,
    SelectedPath,
    StartingOrigins,
    StartingRelationship,
    Storyline,
    StorylineMemory,
    StrategyIdentity,
    SummaryRevision,
    UnsupportedContinuityModeError,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)


class BlockTokenCounter:
    """Count one token per complete rendered extraction block."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Return the number of supplied whole-record blocks.

        Args:
            messages:
                Rendered extraction blocks.

        Returns:
            Number of blocks.
        """

        return len(messages)


def _scope(continuity_id: UUID | None = None) -> ConversationScope:
    """Create complete conversation ownership.

    Args:
        continuity_id:
            Optional stable Storyline owner.

    Returns:
        New conversation scope.
    """

    return ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=continuity_id or uuid4(),
        conversation_id=uuid4(),
    )


def _turn(scope: ConversationScope, sequence: int, label: str) -> CompletedTurn:
    """Create one complete selected turn.

    Args:
        scope:
            Complete conversation ownership.
        sequence:
            Odd user-message sequence.
        label:
            Distinct test content.

    Returns:
        Adjacent complete exchange.
    """

    return CompletedTurn(
        user=Message(
            id=uuid4(),
            scope=scope,
            sequence=sequence,
            role="user",
            content=f"user {label}",
            created_at=NOW,
        ),
        persona=Message(
            id=uuid4(),
            scope=scope,
            sequence=sequence + 1,
            role="persona",
            content=f"persona {label}",
            created_at=NOW,
        ),
    )


def _relationship() -> StartingRelationship:
    """Create a valid starting relationship.

    Returns:
        Immutable relationship snapshot.
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


def _provenance() -> ExtractionProvenance:
    """Create fixed extraction provenance.

    Returns:
        Valid extraction provenance.
    """

    return ExtractionProvenance(
        selector=StrategyIdentity(name="baseline.selector", version="1.0.0"),
        extractor=StrategyIdentity(name="baseline.extractor", version="1.0.0"),
        prompt_schema_version="1.0.0",
        provider="fake",
        model="fake-model",
        configuration=GenerationConfiguration(max_output_tokens=64),
    )


def _memory(
    scope: ConversationScope,
    source_turn: CompletedTurn,
    *,
    occurrence: int,
    learned: int,
    current_state: MemoryRevisionState = MemoryRevisionState.ACTIVE,
    corrected: bool = False,
) -> StorylineMemory:
    """Create one memory with configurable temporal and lifecycle state.

    Args:
        scope:
            Evidence ownership.
        source_turn:
            Supporting selected turn.
        occurrence:
            Assertion scene position.
        learned:
            Learning scene position.
        current_state:
            Requested active or excluded current state.
        corrected:
            Whether the current active revision is user-authored.

    Returns:
        Complete logical-memory lineage.
    """

    memory_id = uuid4()
    scene_id = uuid4()
    evidence = MemoryEvidence(
        id=uuid4(),
        scope=scope,
        scene_id=scene_id,
        user_message_id=source_turn.user.id,
        persona_message_id=source_turn.persona.id,
        persona_checkpoint=source_turn.persona.sequence,
        occurrence=ScenePosition(scene_id=uuid4(), position=occurrence),
        learned=ScenePosition(scene_id=scene_id, position=learned),
        extraction=_provenance(),
        created_at=NOW,
    )
    first = MemoryRevision(
        id=uuid4(),
        memory_id=memory_id,
        continuity_id=scope.continuity_id,
        revision=1,
        predecessor_id=None,
        subject=f"subject {memory_id}",
        content="remembered content",
        state=(
            MemoryRevisionState.SUPERSEDED
            if corrected or current_state == MemoryRevisionState.EXCLUDED
            else MemoryRevisionState.ACTIVE
        ),
        authorship=MemoryAuthorship.EXTRACTED,
        kind=MemoryRevisionKind.EXTRACTION,
        source=evidence,
        created_at=NOW,
    )
    revisions: tuple[MemoryRevision, ...] = (first,)
    current = first
    if corrected or current_state == MemoryRevisionState.EXCLUDED:
        current = MemoryRevision(
            id=uuid4(),
            memory_id=memory_id,
            continuity_id=scope.continuity_id,
            revision=2,
            predecessor_id=first.id,
            subject=first.subject,
            content=("corrected content" if corrected else first.content),
            state=current_state,
            authorship=(MemoryAuthorship.USER if corrected else first.authorship),
            kind=(
                MemoryRevisionKind.USER_CORRECTION
                if corrected
                else MemoryRevisionKind.EXCLUSION
            ),
            source=evidence,
            created_at=NOW,
        )
        revisions = (first, current)
    return StorylineMemory(
        id=memory_id,
        continuity_id=scope.continuity_id,
        current_revision_id=current.id,
        revisions=revisions,
        evidence=(evidence,),
    )


def _context(
    *,
    recent_turns: tuple[CompletedTurn, ...] | None = None,
    memories: tuple[StorylineMemory, ...] | None = None,
) -> MemoryExtractionContext:
    """Create complete eligible selector input.

    Args:
        recent_turns:
            Optional prior selected turns.
        memories:
            Optional eligible memories.

    Returns:
        Immutable extraction context.
    """

    scope = _scope()
    prior = recent_turns or ()
    source_sequence = 1 + 2 * len(prior)
    source = _turn(scope, source_sequence, "source")
    return MemoryExtractionContext(
        scope=scope,
        scene=ScenePosition(scene_id=uuid4(), position=3),
        identity_label="You",
        persona_label="Guide",
        starting_relationship=_relationship(),
        scene_setup="A quiet observatory.",
        summary=None,
        recent_turns=prior,
        eligible_memories=memories or (),
        source_turn=source,
    )


def test_eligibility_applies_ownership_branch_time_and_lifecycle_matrix() -> None:
    """Include corrected selected past facts and reject every ineligible axis."""

    continuity_id = uuid4()
    scope = _scope(continuity_id)
    selected_source = _turn(scope, 1, "selected")
    deselected_source = _turn(scope, 3, "deselected")
    eligible = _memory(scope, selected_source, occurrence=1, learned=2, corrected=True)
    later_occurrence = _memory(scope, selected_source, occurrence=3, learned=3)
    learned_later = _memory(scope, selected_source, occurrence=1, learned=3)
    deselected = _memory(scope, deselected_source, occurrence=1, learned=1)
    excluded = _memory(
        scope,
        selected_source,
        occurrence=1,
        learned=1,
        current_state=MemoryRevisionState.EXCLUDED,
    )
    foreign_scope = _scope()
    foreign_source = _turn(foreign_scope, 1, "foreign")
    foreign = _memory(foreign_scope, foreign_source, occurrence=1, learned=1)
    policy = StorylineMemoryEligibility()
    target = ScenePosition(scene_id=uuid4(), position=2)

    result = policy.select(
        (
            eligible,
            later_occurrence,
            learned_later,
            deselected,
            excluded,
            foreign,
        ),
        continuity_id,
        target,
        frozenset({selected_source.persona.id}),
    )

    assert result == (eligible,)
    assert policy.select((eligible,), continuity_id, target, frozenset()) == ()
    assert policy.select(
        (eligible,),
        continuity_id,
        target,
        frozenset({selected_source.persona.id}),
    ) == (eligible,)


def test_selector_renders_exact_order_and_is_reproducible() -> None:
    """Render mandatory and optional records whole in the accepted order."""

    scope = _scope()
    recent = _turn(scope, 1, "recent")
    source = _turn(scope, 3, "source")
    memory = _memory(scope, recent, occurrence=1, learned=1)
    context = MemoryExtractionContext(
        scope=scope,
        scene=ScenePosition(scene_id=uuid4(), position=2),
        identity_label="You",
        persona_label="Guide",
        starting_relationship=_relationship(),
        scene_setup="At the station.",
        summary=None,
        recent_turns=(recent,),
        eligible_memories=(memory,),
        source_turn=source,
    )
    selector = BaselineMemoryContextSelector(BlockTokenCounter())
    budget = ExtractionBudget(input_tokens=16, fixed_overhead_tokens=1)

    first = selector.select(context, budget)
    second = selector.select(context, budget)

    assert first == second
    assert first.selector == selector.strategy_id
    assert first.included_turn_ids == (recent.persona.id,)
    assert first.included_memory_ids == (memory.id,)
    assert tuple(block.splitlines()[0] for block in first.prompt) == (
        "[identity]",
        "[persona]",
        "[starting relationship]",
        "[scene setup]",
        f"[recent turn:{recent.persona.id}]",
        f"[memory:{memory.id}]",
        f"[new evidence:{source.persona.id}]",
    )
    assert first.token_count == 8


def test_selector_keeps_source_and_chooses_newest_turn_whole() -> None:
    """Omit older optional records while retaining exact mandatory evidence."""

    scope = _scope()
    older = _turn(scope, 1, "older")
    newer = _turn(scope, 3, "newer")
    source = _turn(scope, 5, "source")
    memory = _memory(scope, older, occurrence=1, learned=1)
    context = MemoryExtractionContext(
        scope=scope,
        scene=ScenePosition(scene_id=uuid4(), position=2),
        identity_label="You",
        persona_label="Guide",
        starting_relationship=_relationship(),
        scene_setup="At the station.",
        summary=None,
        recent_turns=(older, newer),
        eligible_memories=(memory,),
        source_turn=source,
    )
    selector = BaselineMemoryContextSelector(BlockTokenCounter())

    result = selector.select(
        context, ExtractionBudget(input_tokens=7, fixed_overhead_tokens=1)
    )

    assert result.included_turn_ids == (newer.persona.id,)
    assert result.omitted_turn_ids == (older.persona.id,)
    assert result.included_memory_ids == ()
    assert result.omitted_memory_ids == (memory.id,)
    assert result.prompt[-1].startswith(f"[new evidence:{source.persona.id}]")
    assert result.token_count == 7


def test_selector_admits_compatible_summary_before_recent_turns() -> None:
    """Place an admitted compatible summary at its accepted block position."""

    context = _context()
    summary = SummaryRevision.model_construct(
        id=uuid4(),
        scope=context.scope,
        content="Earlier selected events.",
    )
    context = context.model_copy(update={"summary": summary})
    selector = BaselineMemoryContextSelector(BlockTokenCounter())

    result = selector.select(
        context, ExtractionBudget(input_tokens=7, fixed_overhead_tokens=1)
    )

    assert result.summary_included
    assert result.prompt[4] == "[summary]\nEarlier selected events."
    assert result.prompt[-1].startswith(
        f"[new evidence:{context.source_turn.persona.id}]"
    )


def test_selector_reports_capacity_failure_and_empty_optional_context() -> None:
    """Fail before extraction when mandatory blocks do not fit."""

    selector = BaselineMemoryContextSelector(BlockTokenCounter())
    context = _context()
    fitting = selector.select(
        context, ExtractionBudget(input_tokens=6, fixed_overhead_tokens=1)
    )

    assert fitting.included_turn_ids == ()
    assert fitting.included_memory_ids == ()
    assert fitting.token_count == 6
    with pytest.raises(ContextCapacityError, match="Mandatory Storyline"):
        selector.select(
            context, ExtractionBudget(input_tokens=5, fixed_overhead_tokens=1)
        )


def test_response_selector_has_independent_order_budget_and_exact_accounting() -> None:
    """Select whole response records without inheriting extraction priority."""

    scope = _scope()
    source = _turn(scope, 1, "source")
    first = _memory(scope, source, occurrence=1, learned=1)
    second = _memory(scope, source, occurrence=1, learned=1)
    selector = BaselineResponseMemorySelector()

    result = selector.select(
        (second, first),
        ResponseMemoryBudget(input_tokens=1),
        BlockTokenCounter(),
    )

    expected_order = tuple(
        sorted(
            (first, second),
            key=lambda memory: (memory.current.subject.casefold(), str(memory.id)),
        )
    )
    assert result.selector == StrategyIdentity(
        name="baseline.storyline_response_memory", version="1.0.0"
    )
    assert result.eligible_memory_ids == tuple(memory.id for memory in expected_order)
    assert result.included_memories == expected_order[:1]
    assert result.omitted_memory_ids == (expected_order[1].id,)
    assert result.token_count == 1


def test_response_service_uses_same_branch_and_time_eligibility_query() -> None:
    """Query repository eligibility from all selected scenes through the target."""

    scope = _scope()
    source = _turn(scope, 1, "selected")
    memory = _memory(scope, source, occurrence=1, learned=1)
    storyline = Storyline(
        id=scope.continuity_id,
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        name="Eligible past",
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=_relationship(),
        revision=1,
    )
    scene = Scene(
        id=uuid4(),
        scope=scope,
        position=1,
        details=SceneDetails(
            title="Arrival",
            setup="At the platform.",
            response_style=ResponseStyleSnapshot(
                name="stage6.default",
                version="1.0.0",
                instruction="Respond naturally.",
            ),
        ),
        setup_locked=True,
    )
    path = SelectedPath.model_construct(
        scope=scope,
        selected_leaf_id=source.persona.id,
        messages=(
            MessageNode.model_construct(
                id=source.user.id,
                scope=scope,
                parent_id=None,
                role="user",
                content=source.user.content,
                created_at=NOW,
                response_provenance=None,
            ),
            MessageNode.model_construct(
                id=source.persona.id,
                scope=scope,
                parent_id=source.user.id,
                role="persona",
                content=source.persona.content,
                created_at=NOW,
                response_provenance=None,
            ),
        ),
    )
    scenes = Mock()
    scenes.list.return_value = SceneSequence(storyline=storyline, scenes=(scene,))
    conversations = Mock()
    conversations.selected_path.return_value = path
    memories = Mock()
    memories.list_eligible.return_value = (memory,)
    service = StorylineResponseMemoryService(
        scenes,
        conversations,
        memories,
        BaselineResponseMemorySelector(),
        ResponseMemoryBudget(input_tokens=4),
    )

    result = service.select(storyline, scene, BlockTokenCounter())

    memories.list_eligible.assert_called_once_with(
        storyline.id,
        scene.position,
        frozenset({source.persona.id}),
    )
    assert result.included_memories == (memory,)


def test_snapshot_service_builds_owned_storyline_context_and_rejects_ongoing() -> None:
    """Build from owned readers while keeping non-Storyline modes unavailable."""

    scope = _scope()
    scene_id = uuid4()
    target = ConversationTarget(
        scope=scope, mode=ContinuityMode.STORYLINE, scene_id=scene_id
    )
    storyline = Storyline(
        id=scope.continuity_id,
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        name="A test storyline",
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=_relationship(),
        revision=1,
    )
    style = ResponseStyleSnapshot(
        name="stage6.default",
        version="1.0.0",
        instruction="Respond naturally.",
    )
    scene = Scene(
        id=scene_id,
        scope=scope,
        position=1,
        details=SceneDetails(
            title="Arrival",
            setup="At the platform.",
            response_style=style,
        ),
        setup_locked=True,
    )
    source = _turn(scope, 1, "source")
    path = SelectedPath.model_construct(
        scope=scope,
        selected_leaf_id=source.persona.id,
        messages=(
            MessageNode.model_construct(
                id=source.user.id,
                scope=scope,
                parent_id=None,
                role="user",
                content=source.user.content,
                created_at=NOW,
                response_provenance=None,
            ),
            MessageNode.model_construct(
                id=source.persona.id,
                scope=scope,
                parent_id=source.user.id,
                role="persona",
                content=source.persona.content,
                created_at=NOW,
                response_provenance=None,
            ),
        ),
    )
    memory = _memory(scope, source, occurrence=1, learned=1)
    identities = Mock()
    identities.get.return_value = Identity(
        id=scope.identity_id,
        details=IdentityDetails(name="Alex"),
        revision=1,
        is_frozen=True,
        is_default=False,
    )
    personas = Mock()
    personas.get.return_value = Persona(
        id=scope.persona_id,
        core=PersonaCore(name="Morgan", definition="A careful guide."),
        revision=1,
        is_frozen=True,
    )
    storylines = Mock()
    storylines.get.return_value = storyline
    scenes = Mock()
    scenes.get.return_value = scene
    scenes.list.return_value = SceneSequence(storyline=storyline, scenes=(scene,))
    conversations = Mock()
    conversations.selected_path.return_value = path
    summaries = Mock()
    summaries.get_current.return_value = None
    memories = Mock()
    memories.list.return_value = (memory,)
    service = StorylineExtractionContextService(
        identities,
        personas,
        storylines,
        scenes,
        conversations,
        summaries,
        memories,
        StorylineMemoryEligibility(),
        BaselineMemoryContextSelector(BlockTokenCounter()),
    )

    result = service.build(
        target,
        source.persona.id,
        ExtractionBudget(input_tokens=12, fixed_overhead_tokens=1),
    )

    assert result.context.identity_label == "Alex"
    assert result.context.persona_label == "Morgan"
    assert result.context.scene_setup == "At the platform."
    assert result.context.source_turn == source
    assert result.context.eligible_memories == (memory,)
    assert result.prompt[-1].startswith(f"[new evidence:{source.persona.id}]")

    ongoing = ConversationTarget(scope=scope, mode=ContinuityMode.ONGOING)
    with pytest.raises(UnsupportedContinuityModeError, match="Storyline scene"):
        service.build(
            ongoing,
            source.persona.id,
            ExtractionBudget(input_tokens=12, fixed_overhead_tokens=1),
        )
