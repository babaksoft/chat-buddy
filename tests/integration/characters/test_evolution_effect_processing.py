"""Completed-turn evolution orchestration and recovery coverage."""

from __future__ import annotations

from uuid import uuid5

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    BASELINE_EVOLUTION_CONFIGURATION,
    BaselineEvolutionSnapshotSelector,
    ContinuityService,
    ContinuityStableEvolutionConfigurationResolver,
    ConversationService,
    EvolutionEffectService,
    NoChangeEvolutionStrategy,
    StrictBaselineEvolutionThresholdPolicy,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    EvolutionConfiguration,
    EvolutionEffectConflictError,
    EvolutionEffectState,
    EvolutionProposal,
    EvolutionScope,
    EvolutionSnapshot,
    EvolutionSnapshotBudget,
    EvolutionStrategy,
    RelationshipDynamic,
    SetDynamicCommand,
    StrategyIdentity,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbEvolutionRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineMemoryRepository,
    DbStorylineRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import Utf8TokenCounter
from tests.characters_support import FakeResponse, ongoing_target, registry, start


class ApplyingEvolutionStrategy:
    """Deterministically propose an immediate tense interaction dynamic."""

    strategy_id = StrategyIdentity(name="test.applying", version="1.0.0")

    def __init__(self, configuration: EvolutionConfiguration) -> None:
        """Bind exact proposal provenance.

        Args:
            configuration:
                Configuration expected by the orchestration seam.
        """

        self._configuration = configuration

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Propose one traceable immediate dynamic change.

        Args:
            snapshot:
                Current state and exact selected evidence.

        Returns:
            Deterministic bounded proposal.
        """

        return EvolutionProposal(
            id=uuid5(snapshot.source.persona_message_id, "test.applying:1.0.0"),
            scope=snapshot.scope,
            expected_relationship_revision=snapshot.relationship.revision,
            expected_adaptation_revision=snapshot.persona_adaptations.revision,
            source=snapshot.source,
            provenance=self._configuration.provenance(),
            commands=(
                SetDynamicCommand(
                    expected=snapshot.relationship.dynamic,
                    value=RelationshipDynamic.TENSE,
                    rationale="The exchange explicitly describes current tension.",
                    sources=(snapshot.source,),
                ),
            ),
        )


class FailOnceEvolutionStrategy:
    """Raise once before returning the configured no-change proposal."""

    strategy_id = BASELINE_EVOLUTION_CONFIGURATION.strategy

    def __init__(self) -> None:
        """Initialize one transient failure."""

        self._failed = False
        self._delegate = NoChangeEvolutionStrategy()

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Fail the first invocation and delegate later calls.

        Args:
            snapshot:
                Immutable evolution snapshot.

        Returns:
            Baseline no-change proposal after the transient failure.

        Raises:
            RuntimeError:
                On the first invocation only.
        """

        if not self._failed:
            self._failed = True
            raise RuntimeError("transient strategy failure")
        return self._delegate.propose(snapshot)


def test_completed_turn_applies_one_effect_and_reuses_it_on_repeat(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Commit accepted events and projections once for repeated processing.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    configuration = BASELINE_EVOLUTION_CONFIGURATION.model_copy(
        update={"strategy": ApplyingEvolutionStrategy.strategy_id}
    )
    strategy = ApplyingEvolutionStrategy(configuration)
    processor = _processor(factory, configuration, strategy)
    app = _conversation_service(factory, processor)
    target = ongoing_target(scope)

    attempt = app.send(target, SubmittedInput(content="This conflict feels tense."))
    assert "".join(app.stream(target, attempt.id)) == "Hello there"

    history = app.history(target)
    persona_message = history.messages[-1]
    repository = DbEvolutionRepository(factory)
    evolution_scope = EvolutionScope(
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        continuity_id=scope.continuity_id,
    )
    effect = repository.get_effect(evolution_scope, persona_message.id)
    assert effect.state == EvolutionEffectState.APPLIED
    assert len(repository.list_events(evolution_scope)) == 1
    assert repository.get_projections(evolution_scope).relationship.dynamic == "tense"

    restarted = _processor(
        factory, configuration, ApplyingEvolutionStrategy(configuration)
    )
    assert restarted.process(target, persona_message.id) == effect
    assert len(repository.list_events(evolution_scope)) == 1


def test_failed_evolution_stays_retryable_without_losing_response(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep the committed response and resume its reserved effect after failure.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    strategy = FailOnceEvolutionStrategy()
    processor = _processor(factory, BASELINE_EVOLUTION_CONFIGURATION, strategy)
    app = _conversation_service(factory, processor)
    target = ongoing_target(scope)

    attempt = app.send(target, SubmittedInput(content="Nothing should change."))
    assert "".join(app.stream(target, attempt.id)) == "Hello there"
    history = app.history(target)
    assert history.messages[-1].role == "persona"
    assert history.attempts[-1].status == "completed"

    evolution_scope = EvolutionScope(
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        continuity_id=scope.continuity_id,
    )
    repository = DbEvolutionRepository(factory)
    source_id = history.messages[-1].id
    assert (
        repository.get_effect(evolution_scope, source_id).state
        == EvolutionEffectState.RESERVED
    )

    completed = processor.process(target, source_id)
    assert completed.state == EvolutionEffectState.NO_CHANGE
    assert repository.list_events(evolution_scope) == ()


def test_archived_continuity_does_not_reserve_an_evolution_effect(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject archived manual processing before projection or effect persistence.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    app = _conversation_service(factory, None)
    target = ongoing_target(scope)
    attempt = app.send(target, SubmittedInput(content="A complete exchange."))
    list(app.stream(target, attempt.id))
    source_id = app.history(target).messages[-1].id
    ContinuityService(DbContinuityRepository(factory)).archive(
        scope.identity_id, scope.persona_id, scope.continuity_id
    )
    processor = _processor(
        factory,
        BASELINE_EVOLUTION_CONFIGURATION,
        NoChangeEvolutionStrategy(),
    )

    with pytest.raises(ArchivedContinuityError):
        processor.process(target, source_id)

    evolution_scope = EvolutionScope(
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        continuity_id=scope.continuity_id,
    )
    with pytest.raises(EvolutionEffectConflictError, match="does not exist"):
        DbEvolutionRepository(factory).get_effect(evolution_scope, source_id)


def _processor(
    factory: sessionmaker[Session],
    configuration: EvolutionConfiguration,
    strategy: EvolutionStrategy,
) -> EvolutionEffectService:
    """Compose real repositories around one test strategy.

    Args:
        factory:
            Isolated Characters sessions.
        configuration:
            Exact version identities for the effect.
        strategy:
            Replaceable proposal implementation.

    Returns:
        Ready completed-turn evolution processor.
    """

    conversations = DbConversationRepository(factory)
    continuities = DbContinuityRepository(factory)
    storylines = DbStorylineRepository(factory)
    scenes = DbSceneRepository(factory)
    evolution = DbEvolutionRepository(factory)
    selector = BaselineEvolutionSnapshotSelector(
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        continuities,
        storylines,
        scenes,
        conversations,
        DbSummaryRepository(factory),
        DbStorylineMemoryRepository(factory),
        evolution,
        Utf8TokenCounter(),
        EvolutionSnapshotBudget(input_tokens=200_000, fixed_overhead_tokens=64),
    )
    return EvolutionEffectService(
        conversations,
        continuities,
        storylines,
        scenes,
        evolution,
        selector,
        ContinuityStableEvolutionConfigurationResolver((configuration,)),
        strategy,
        StrictBaselineEvolutionThresholdPolicy(),
    )


def _conversation_service(
    factory: sessionmaker[Session], evolution: EvolutionEffectService | None
) -> ConversationService:
    """Compose response orchestration with optional automatic evolution.

    Args:
        factory:
            Isolated Characters sessions.
        evolution:
            Optional post-completion processor.

    Returns:
        Conversation service backed by real repositories and a fake provider.
    """

    return ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        registry(FakeResponse()),
        evolution=evolution,
    )
