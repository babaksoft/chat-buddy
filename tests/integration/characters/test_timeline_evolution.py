"""Entry-backed Timeline inference, temporal eligibility, replay, and correction."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    BASELINE_EVOLUTION_CONFIGURATION,
    ConversationService,
    DeterministicFixtureEvolutionStrategy,
    EvolutionEffectService,
    EvolutionEntryHistory,
    EvolutionProjectionService,
    NoChangeEvolutionStrategy,
    ResponseStyleService,
    TimelineConversationAdapter,
    TimelineDayService,
)
from chat_buddy.characters.domain import (
    AdaptationFacet,
    ArchivedContinuityError,
    ContinuityMode,
    ConversationTarget,
    CreateMemoryCommand,
    EntryEvolutionEvidenceReference,
    EvolutionEffectConflictError,
    EvolutionEffectState,
    EvolutionProposal,
    EvolutionScope,
    EvolutionSnapshot,
    GraphAction,
    GraphActionRequest,
    MemoryDelta,
    MemoryEvidence,
    RelationshipDynamic,
    SetDynamicCommand,
    SetPersonaAdaptationCommand,
    StrategyIdentity,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import (
    EvolutionEventModel,
    TimelineDayModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityEntryRepository,
    DbContinuityRepository,
    DbConversationRepository,
    DbEvolutionRepository,
    DbIdentityRepository,
    DbMemoryExtractionRepository,
    DbPersonaRepository,
    DbResponseStyleRepository,
    DbStorylineRepository,
    DbSummaryRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)
from tests.characters_support import FakeResponse
from tests.integration.characters.test_evolution_effect_processing import (
    ApplyingEvolutionStrategy,
    FailOnceEvolutionStrategy,
    _processor,
)
from tests.integration.characters.test_evolution_snapshots import _selector
from tests.integration.characters.test_storyline_memory_repositories import _provenance
from tests.integration.characters.test_timeline_conversations import (
    FakeSummary,
    MutableClock,
    _registry,
    _start_day,
)


def test_timeline_inference_failure_preserves_response_and_retries_once(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep the visible response and resume the exact reserved effect after restart.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, target = _start_day(factory, clock, responses, FakeSummary(), "Hello")
    strategy = FailOnceEvolutionStrategy()
    processor = _processor(factory, BASELINE_EVOLUTION_CONFIGURATION, strategy)
    app = _conversation(factory, clock, responses, processor)
    attempt = app.history(target).attempts[0]
    assert list(app.stream(target, attempt.id)) == ["Hello", " there"]
    source = _source(factory, target)
    repository = DbEvolutionRepository(factory)
    effect = repository.get_effect(source.scope, source.persona_message_id)
    assert effect.state == EvolutionEffectState.RESERVED
    assert app.history(target).messages[-1].id == source.persona_message_id
    restarted = _processor(factory, BASELINE_EVOLUTION_CONFIGURATION, strategy)
    terminal = restarted.process(target, source.persona_message_id)
    assert terminal.id == effect.id
    assert terminal.state == EvolutionEffectState.NO_CHANGE
    assert restarted.process(target, source.persona_message_id) == terminal
    assert len(repository.list_effects(source.scope)) == 1
    assert repository.list_events(source.scope) == ()


def test_timeline_day_boundaries_replay_corrections_and_future_exclusion(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Carry settled state across an offline gap without prior or future transcript.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, first = _start_day(
        factory, clock, responses, FakeSummary(), "I feel tense today"
    )
    configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={"strategy": ApplyingEvolutionStrategy.strategy_id}
    )
    processor = _processor(
        factory, configuration, ApplyingEvolutionStrategy(configuration)
    )
    app = _conversation(factory, clock, responses, processor)
    list(app.stream(first, app.history(first).attempts[0].id))
    source = _source(factory, first)
    repository = DbEvolutionRepository(factory)
    event = repository.list_events(source.scope)[0]
    assert event.command.sources == (source,)
    assert event.provenance == configuration.provenance()
    assert (
        repository.get_projections(source.scope).relationship.dynamic
        == RelationshipDynamic.TENSE
    )

    clock.value = datetime(2026, 11, 8, 8, tzinfo=UTC)
    second, attempt_id = _next_day(factory, clock, responses, first)
    # Complete without another inference to inspect the exact next snapshot.
    plain_app = _conversation(factory, clock, responses)
    list(plain_app.stream(second, attempt_id))
    second_source = _source(factory, second)
    snapshot = _selector(factory, repository).select(source.scope, second_source)
    assert snapshot.relationship.dynamic == RelationshipDynamic.TENSE
    assert tuple(item.reference for item in snapshot.evidence) == (second_source,)
    days = DbTimelineDayRepository(factory)
    closed = days.get(first.scope, source.entry.entry_id)
    assert closed.is_closed
    assert closed.settled_selected_leaf_id == source.persona_message_id
    assert second_source.entry.position == 2

    # Later relationship and persona state must not leak into an earlier Entry.
    later_configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={
            "strategy": StrategyIdentity(name="fixture.deterministic", version="1.0.0")
        }
    )
    strategy = DeterministicFixtureEvolutionStrategy(
        {
            source.scope.continuity_id: (
                SetDynamicCommand(
                    expected=RelationshipDynamic.TENSE,
                    value=RelationshipDynamic.AWKWARD,
                    rationale="The new day is awkward",
                    sources=(second_source,),
                ),
                SetPersonaAdaptationCommand(
                    facet=AdaptationFacet.COMMUNICATION_STYLE,
                    expected=None,
                    value="Offer concise explanations",
                    rationale="An explicit conversational preference",
                    sources=(second_source,),
                ),
            )
        },
        later_configuration,
    )
    later = _processor(factory, later_configuration, strategy)
    assert (
        later.process(second, second_source.persona_message_id).state
        == EvolutionEffectState.APPLIED
    )
    assert repository.get_projections(source.scope).persona_adaptations.adaptations
    earlier = _selector(factory, repository).select(source.scope, source)
    assert earlier.relationship.dynamic == RelationshipDynamic.TENSE
    assert earlier.persona_adaptations.adaptations == ()
    replay = _replay(factory)
    state = replay.rebuild(source.scope)
    corrected = replay.replace(
        source.scope,
        event.id,
        SetDynamicCommand(
            expected=RelationshipDynamic.NEUTRAL,
            value=RelationshipDynamic.AWKWARD,
            rationale="Correct the interpretation",
            sources=event.command.sources,
        ),
        state.relationship.revision,
        state.persona_adaptations.revision,
        "The interaction was awkward",
    )
    assert corrected.relationship.dynamic == RelationshipDynamic.AWKWARD
    assert repository.list_events(source.scope)[0] == event
    replacement = repository.list_corrections(source.scope)[0].replacement
    assert replacement is not None and replacement.sources == (source,)
    assert (
        _selector(factory, repository)
        .select(source.scope, second_source)
        .relationship.dynamic
        == RelationshipDynamic.AWKWARD
    )
    assert _replay(factory).rebuild(source.scope).relationship == corrected.relationship
    assert (
        repository.list_events(
            EvolutionScope(
                identity_id=source.scope.identity_id,
                persona_id=source.scope.persona_id,
                continuity_id=uuid4(),
            )
        )
        == ()
    )


def test_timeline_open_day_alternative_rebuilds_and_rejects_unselected_evidence(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Rebuild both projections when switching selected open-day alternatives.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, target = _start_day(factory, clock, responses, FakeSummary(), "I feel tense")
    configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={"strategy": ApplyingEvolutionStrategy.strategy_id}
    )
    applying = _processor(
        factory, configuration, ApplyingEvolutionStrategy(configuration)
    )
    app = _conversation(factory, clock, responses, applying)
    list(app.stream(target, app.history(target).attempts[0].id))
    original = _source(factory, target)
    neutral = _processor(
        factory, BASELINE_EVOLUTION_CONFIGURATION, NoChangeEvolutionStrategy()
    )
    alternative_app = _conversation(factory, clock, responses, neutral)
    retry = alternative_app.retry_completed_response(target)
    list(alternative_app.stream(target, retry.id))
    selected = _source(factory, target)
    repository = DbEvolutionRepository(factory)
    assert (
        repository.get_projections(original.scope).relationship.dynamic
        == RelationshipDynamic.NEUTRAL
    )
    with pytest.raises(ValueError, match="selected"):
        applying.process(target, original.persona_message_id)
    alternative_app.select_alternative(
        target, original.persona_message_id, selected.persona_message_id
    )
    assert (
        repository.get_projections(original.scope).relationship.dynamic
        == RelationshipDynamic.TENSE
    )
    assert len(repository.list_events(original.scope)) == 1
    forged = original.model_copy(
        update={"entry": original.entry.model_copy(update={"position": 99})}
    )
    with pytest.raises(EvolutionEffectConflictError):
        repository.reserve(forged, configuration.provenance())
    timelines = DbTimelineRepository(factory)
    timeline = timelines.get(
        original.scope.identity_id,
        original.scope.persona_id,
        original.scope.continuity_id,
    )
    timelines.archive(
        timeline.identity_id, timeline.persona_id, timeline.id, timeline.revision
    )
    with pytest.raises(ArchivedContinuityError):
        applying.process(target, original.persona_message_id)


@pytest.mark.parametrize("corruption", ("entry_position", "settled_ancestry"))
def test_timeline_replay_rejects_contradictory_persisted_provenance(
    characters_session_factory: sessionmaker[Session], corruption: str
) -> None:
    """Fail closed when persisted Entry ownership or settled ancestry contradicts events.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
        corruption:
            Persistence inconsistency introduced to exercise recovery validation.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, target = _start_day(factory, clock, responses, FakeSummary(), "I feel tense")
    configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={"strategy": ApplyingEvolutionStrategy.strategy_id}
    )
    processor = _processor(
        factory, configuration, ApplyingEvolutionStrategy(configuration)
    )
    app = _conversation(factory, clock, responses, processor)
    list(app.stream(target, app.history(target).attempts[0].id))
    source = _source(factory, target)
    repository = DbEvolutionRepository(factory)
    event = repository.list_events(source.scope)[0]
    clock.value = datetime(2026, 11, 3, 8, tzinfo=UTC)
    _next_day(factory, clock, responses, target)
    with factory() as session, session.begin():
        if corruption == "entry_position":
            command = event.command.model_dump(mode="json")
            command["sources"][0]["entry"]["position"] = 99
            session.execute(
                update(EvolutionEventModel)
                .where(EvolutionEventModel.id == event.id)
                .values(command=command)
            )
        else:
            session.execute(
                update(TimelineDayModel)
                .where(TimelineDayModel.id == source.entry.entry_id)
                .values(settled_selected_leaf_id=source.user_message_id)
            )
    with pytest.raises((ValueError, EvolutionEffectConflictError)):
        _replay(factory).rebuild(source.scope)


def test_timeline_snapshot_admits_prior_memory_only_with_exact_selected_sources(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Admit prior memory through settled evidence and keep future knowledge out.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, first = _start_day(factory, clock, responses, FakeSummary(), "I prefer tea")
    app = _conversation(factory, clock, responses)
    list(app.stream(first, app.history(first).attempts[0].id))
    source = _source(factory, first)
    extraction = DbMemoryExtractionRepository(factory)
    effect = extraction.reserve(
        first.scope,
        ContinuityMode.TIMELINE,
        source.entry.entry_id,
        source.persona_message_id,
    )
    provenance = _provenance()
    evidence = MemoryEvidence(
        id=uuid4(),
        scope=first.scope,
        entry_id=source.entry.entry_id,
        user_message_id=source.user_message_id,
        persona_message_id=source.persona_message_id,
        persona_checkpoint=source.persona_sequence,
        occurrence=source.entry,
        learned=source.entry,
        extraction=provenance,
        created_at=clock.now(),
    )
    extraction.apply(
        effect.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=first.scope,
            source_persona_message_id=source.persona_message_id,
            extractor=provenance.extractor,
            commands=(
                CreateMemoryCommand(
                    subject="drink preference",
                    content="The identity prefers tea.",
                    occurrence=source.entry,
                    evidence=evidence,
                ),
            ),
        ),
        provenance,
    )
    clock.value = datetime(2026, 11, 3, 8, tzinfo=UTC)
    second, attempt = _next_day(factory, clock, responses, first)
    list(app.stream(second, attempt))
    second_source = _source(factory, second)
    snapshot = _selector(factory, DbEvolutionRepository(factory)).select(
        source.scope, second_source
    )
    assert len(snapshot.memories) == 1
    assert snapshot.memories[0].sources == (source,)
    assert snapshot.memories[0].content == "The identity prefers tea."
    assert snapshot.source == second_source
    assert snapshot.evidence[0].reference == source
    assert snapshot.evidence[-1].reference == second_source


@pytest.mark.parametrize("race", ("branch", "archive"))
def test_timeline_branch_race_keeps_inference_retryable_without_stale_events(
    characters_session_factory: sessionmaker[Session],
    race: str,
) -> None:
    """Reject inference when selection or lifecycle changes before commit.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
        race:
            Selection or lifecycle transition during inference.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    _, target = _start_day(factory, clock, responses, FakeSummary(), "I feel tense")
    app = _conversation(factory, clock, responses)
    list(app.stream(target, app.history(target).attempts[0].id))
    original = _source(factory, target)
    retry = app.retry_completed_response(target)
    list(app.stream(target, retry.id))
    alternative = _source(factory, target)
    configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={"strategy": ApplyingEvolutionStrategy.strategy_id}
    )
    delegate = ApplyingEvolutionStrategy(configuration)

    def propose(snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Switch selected history after selection and before committing inference.

        Args:
            snapshot:
                Already selected inference inputs.

        Returns:
            Proposal whose source became unselected during inference.
        """

        proposal = delegate.propose(snapshot)
        if race == "archive":
            timelines = DbTimelineRepository(factory)
            timeline = timelines.get(
                target.scope.identity_id,
                target.scope.persona_id,
                target.scope.continuity_id,
            )
            timelines.archive(
                timeline.identity_id,
                timeline.persona_id,
                timeline.id,
                timeline.revision,
            )
        else:
            DbConversationRepository(factory).apply_action(
                GraphActionRequest(
                    scope=target.scope,
                    action=GraphAction.ALTERNATIVE_SELECTION,
                    expected_selected_leaf_id=alternative.persona_message_id,
                    target_message_id=original.persona_message_id,
                )
            )
        return proposal

    strategy = Mock()
    strategy.strategy_id = ApplyingEvolutionStrategy.strategy_id
    strategy.propose.side_effect = propose
    processor = _processor(factory, configuration, strategy)
    expected_error = (
        ArchivedContinuityError if race == "archive" else EvolutionEffectConflictError
    )
    with pytest.raises(expected_error):
        processor.process(target, alternative.persona_message_id)
    repository = DbEvolutionRepository(factory)
    assert repository.list_events(alternative.scope) == ()
    assert (
        repository.get_effect(alternative.scope, alternative.persona_message_id).state
        == EvolutionEffectState.RESERVED
    )
    assert len(DbConversationRepository(factory).graph(target.scope).nodes) == 3


def _source(
    factory: sessionmaker[Session], target: ConversationTarget
) -> EntryEvolutionEvidenceReference:
    """Read the exact selected whole-turn checkpoint.

    Args:
        factory:
            Isolated Characters sessions.
        target:
            Owned Timeline Day target.

    Returns:
        Exact selected Entry-backed source.
    """

    path = DbConversationRepository(factory).selected_path(target.scope)
    assert target.entry_id is not None
    entry = DbContinuityEntryRepository(factory).get(target.scope, target.entry_id)
    return EntryEvolutionEvidenceReference(
        scope=EvolutionScope(
            identity_id=target.scope.identity_id,
            persona_id=target.scope.persona_id,
            continuity_id=target.scope.continuity_id,
        ),
        conversation_id=target.scope.conversation_id,
        entry=entry.entry_position,
        user_message_id=path.messages[-2].id,
        user_sequence=len(path.messages) - 1,
        persona_message_id=path.messages[-1].id,
        persona_sequence=len(path.messages),
    )


def _replay(factory: sessionmaker[Session]) -> EvolutionProjectionService:
    """Compose a fresh replay service with exact Entry and Day validation.

    Args:
        factory:
            Isolated Characters sessions.

    Returns:
        Ready replay and correction operations.
    """

    conversations = DbConversationRepository(factory)
    return EvolutionProjectionService(
        DbEvolutionRepository(factory),
        DbContinuityRepository(factory),
        conversations,
        DbStorylineRepository(factory),
        timelines=DbTimelineRepository(factory),
        entry_history=EvolutionEntryHistory(
            DbContinuityEntryRepository(factory),
            conversations,
            DbTimelineDayRepository(factory),
        ),
    )


def _conversation(
    factory: sessionmaker[Session],
    clock: MutableClock,
    responses: FakeResponse,
    evolution: EvolutionEffectService | None = None,
) -> ConversationService:
    """Compose real Timeline conversation orchestration and optional inference.

    Args:
        factory:
            Isolated Characters sessions.
        clock:
            Deterministic calendar instant.
        responses:
            Fake response provider.
        evolution:
            Optional post-response inference.

    Returns:
        Conversation service with projection rebuilding enabled.
    """

    conversations = DbConversationRepository(factory)
    return ConversationService(
        conversations,
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        _registry(responses, FakeSummary()),
        ResponseStyleService(DbResponseStyleRepository(factory)),
        timeline_adapter=TimelineConversationAdapter(
            DbTimelineRepository(factory),
            DbTimelineDayRepository(factory),
            conversations,
            clock,
        ),
        evolution=evolution,
        evolution_rebuilder=_replay(factory),
    )


def _next_day(
    factory: sessionmaker[Session],
    clock: MutableClock,
    responses: FakeResponse,
    previous: ConversationTarget,
) -> tuple[ConversationTarget, UUID]:
    """Reserve a later interacting day without placeholder records.

    Args:
        factory:
            Isolated Characters sessions.
        clock:
            Advanced injected instant.
        responses:
            Fake response provider.
        previous:
            Earlier Timeline conversation target.

    Returns:
        New Day target and pending response attempt identifier.
    """

    result = TimelineDayService(
        DbTimelineRepository(factory),
        DbTimelineDayRepository(factory),
        DbConversationRepository(factory),
        clock,
    ).reserve(
        previous.scope.identity_id,
        previous.scope.persona_id,
        previous.scope.continuity_id,
        SubmittedInput(
            content="Today feels awkward; please offer concise explanations"
        ),
        _registry(responses, FakeSummary()).resolve_default("response"),
    )
    assert result.day is not None and result.attempt is not None
    return (
        ConversationTarget(
            scope=result.day.scope, mode=ContinuityMode.TIMELINE, entry_id=result.day.id
        ),
        result.attempt.id,
    )
