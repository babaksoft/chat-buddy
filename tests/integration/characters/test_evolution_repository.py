"""Evolution effect idempotency, atomicity, and restart coverage."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEffectConflictError,
    EvolutionEffectState,
    EvolutionEvent,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProjectionConflictError,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionScope,
    PersonaAdaptationProjection,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SetTrustCommand,
    StrategyIdentity,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db import (
    CHARACTERS_SCHEMA,
    CharactersBase,
)
from chat_buddy.characters.infrastructure.db.repositories import DbEvolutionRepository
from tests.characters_support import FakeResponse, ongoing_target, service, start


def test_projection_initialization_is_idempotent_across_repository_restarts(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reload identical revision-zero caches and reject conflicting initialization.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    repository, _, relationship, adaptations, _ = _prepared(characters_session_factory)
    created = repository.initialize(relationship, adaptations)
    restarted = DbEvolutionRepository(characters_session_factory)
    assert restarted.initialize(relationship, adaptations) == created
    assert restarted.get_projections(relationship.scope) == created

    conflicting = relationship.model_copy(update={"trust": RelationshipTrust.TRUSTING})
    with pytest.raises(EvolutionProjectionConflictError):
        restarted.initialize(conflicting, adaptations)


def test_effect_reservation_and_no_change_completion_are_restart_safe(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep one effect per checkpoint and return the same terminal audit record.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    repository, source, relationship, adaptations, provenance = _prepared(
        characters_session_factory
    )
    repository.initialize(relationship, adaptations)
    reserved = repository.reserve(source, provenance)
    assert reserved.state == EvolutionEffectState.RESERVED
    assert repository.reserve(source, provenance) == reserved

    changed_provenance = provenance.model_copy(
        update={"model": "other", "provider": "fake"}
    )
    with pytest.raises(EvolutionEffectConflictError):
        repository.reserve(source, changed_provenance)

    proposal = _proposal(source, provenance)
    decision = EvolutionDecision(
        proposal_id=proposal.id, outcome=EvolutionDecisionOutcome.NO_CHANGE
    )
    completed = repository.complete(reserved.id, proposal, decision)
    restarted = DbEvolutionRepository(characters_session_factory)
    assert restarted.get_effect(source.scope, source.persona_message_id) == completed
    assert restarted.complete(reserved.id, proposal, decision) == completed
    assert restarted.list_events(source.scope) == ()
    assert restarted.get_projections(source.scope).relationship == relationship


def test_applied_events_and_both_projection_caches_commit_atomically(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Append accepted commands with contiguous revisions and cache checkpoints.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    repository, source, relationship, adaptations, provenance = _prepared(
        characters_session_factory
    )
    repository.initialize(relationship, adaptations)
    effect = repository.reserve(source, provenance)
    command = SetTrustCommand(
        expected=RelationshipTrust.UNKNOWN,
        value=RelationshipTrust.TRUSTING,
        rationale="The exact turn establishes trust.",
        sources=(source,),
    )
    proposal = _proposal(source, provenance, command)
    event = EvolutionEvent(
        id=uuid4(),
        proposal_id=proposal.id,
        scope=source.scope,
        command=command,
        relationship_revision=1,
        adaptation_revision=0,
        provenance=provenance,
        created_at=datetime.now(UTC),
    )
    decision = EvolutionDecision(
        proposal_id=proposal.id,
        outcome=EvolutionDecisionOutcome.APPLIED,
        events=(event,),
    )
    updated_relationship = relationship.model_copy(
        update={"revision": 1, "trust": RelationshipTrust.TRUSTING}
    )
    completed = repository.complete(
        effect.id,
        proposal,
        decision,
        updated_relationship,
        adaptations,
    )

    assert completed.state == EvolutionEffectState.APPLIED
    assert repository.list_events(source.scope) == (event,)
    projections = DbEvolutionRepository(characters_session_factory).get_projections(
        source.scope
    )
    assert projections.relationship == updated_relationship
    assert projections.persona_adaptations == adaptations
    assert projections.relationship_checkpoint_id == event.id
    assert projections.adaptation_checkpoint_id is None


def test_invalid_applied_projection_rolls_back_effect_and_events(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Leave a reservation retryable when projection consistency validation fails.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    repository, source, relationship, adaptations, provenance = _prepared(
        characters_session_factory
    )
    repository.initialize(relationship, adaptations)
    effect = repository.reserve(source, provenance)
    command = SetTrustCommand(
        expected=RelationshipTrust.UNKNOWN,
        value=RelationshipTrust.TRUSTING,
        rationale="The exact turn establishes trust.",
        sources=(source,),
    )
    proposal = _proposal(source, provenance, command)
    event = EvolutionEvent(
        id=uuid4(),
        proposal_id=proposal.id,
        scope=source.scope,
        command=command,
        relationship_revision=1,
        adaptation_revision=0,
        provenance=provenance,
        created_at=datetime.now(UTC),
    )
    decision = EvolutionDecision(
        proposal_id=proposal.id,
        outcome=EvolutionDecisionOutcome.APPLIED,
        events=(event,),
    )

    with pytest.raises(EvolutionProjectionConflictError):
        repository.complete(
            effect.id,
            proposal,
            decision,
            relationship,
            adaptations,
        )
    assert (
        repository.get_effect(source.scope, source.persona_message_id).state
        == EvolutionEffectState.RESERVED
    )
    assert repository.list_events(source.scope) == ()
    assert repository.get_projections(source.scope).relationship == relationship


def test_concurrent_reservations_converge_on_one_effect(tmp_path: Path) -> None:
    """Resolve racing checkpoint reservations through the unique source constraint.

    Args:
        tmp_path:
            Isolated writable directory for a multi-connection SQLite database.
    """

    database = tmp_path / "evolution.sqlite"
    engine = create_engine(
        f"sqlite:///{database}",
        execution_options={"schema_translate_map": {CHARACTERS_SCHEMA: None}},
    )
    CharactersBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        _, source, _, _, provenance = _prepared(factory)

        def reserve() -> object:
            """Reserve the shared source from an independent repository."""

            return DbEvolutionRepository(factory).reserve(source, provenance)

        with ThreadPoolExecutor(max_workers=2) as pool:
            effects = tuple(pool.map(lambda _: reserve(), range(2)))
        assert effects[0] == effects[1]
    finally:
        engine.dispose()


def _prepared(
    factory: sessionmaker[Session],
) -> tuple[
    DbEvolutionRepository,
    EvolutionEvidenceReference,
    RelationshipProjection,
    PersonaAdaptationProjection,
    EvolutionProvenance,
]:
    """Create one completed Ongoing turn and its revision-zero evolution state.

    Args:
        factory:
            Characters database sessions.

    Returns:
        Repository, source, paired projections, and fixed provenance.
    """

    conversation_scope = start(factory)
    app = service(factory, FakeResponse())
    attempt = app.send(
        ongoing_target(conversation_scope), SubmittedInput(content="I trust you.")
    )
    list(app.stream(ongoing_target(conversation_scope), attempt.id))
    history = app.history(ongoing_target(conversation_scope))
    scope = EvolutionScope(
        identity_id=conversation_scope.identity_id,
        persona_id=conversation_scope.persona_id,
        continuity_id=conversation_scope.continuity_id,
    )
    source = EvolutionEvidenceReference(
        scope=scope,
        kind=EvolutionEvidenceKind.ONGOING_TURN,
        conversation_id=conversation_scope.conversation_id,
        user_message_id=history.messages[0].id,
        user_sequence=1,
        persona_message_id=history.messages[1].id,
        persona_sequence=2,
    )
    relationship = RelationshipProjection(
        scope=scope,
        revision=0,
        social=RelationshipSocialStatus.STRANGER,
        romantic=RelationshipRomanticStatus.NONE,
        dynamic=RelationshipDynamic.NEUTRAL,
        trust=RelationshipTrust.UNKNOWN,
        affection=RelationshipAffection.NEUTRAL,
    )
    adaptations = PersonaAdaptationProjection(scope=scope, revision=0)
    provenance = EvolutionProvenance(
        selector=StrategyIdentity(name="test.selector", version="1.0.0"),
        strategy=StrategyIdentity(name="test.strategy", version="1.0.0"),
        policy=StrategyIdentity(name="test.policy", version="1.0.0"),
        schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
    )
    return DbEvolutionRepository(factory), source, relationship, adaptations, provenance


def _proposal(
    source: EvolutionEvidenceReference,
    provenance: EvolutionProvenance,
    command: SetTrustCommand | None = None,
) -> EvolutionProposal:
    """Build one bounded proposal for the prepared revision-zero state.

    Args:
        source:
            Exact new checkpoint.
        provenance:
            Fixed experimental identities.
        command:
            Optional accepted trust command.

    Returns:
        Valid atomic proposal.
    """

    return EvolutionProposal(
        id=uuid4(),
        scope=source.scope,
        expected_relationship_revision=0,
        expected_adaptation_revision=0,
        source=source,
        provenance=provenance,
        commands=() if command is None else (command,),
    )
