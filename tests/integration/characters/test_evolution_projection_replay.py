"""Evolution projection replay and user correction integration coverage."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import EvolutionProjectionService
from chat_buddy.characters.domain import (
    AdaptationFacet,
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionConflictError,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEvent,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionScope,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SetPersonaAdaptationCommand,
    SetSocialStatusCommand,
    StrategyIdentity,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import (
    PersonaAdaptationProjectionModel,
    RelationshipProjectionModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbEvolutionRepository,
)
from tests.characters_support import FakeResponse, ongoing_target, service, start


def test_exclusion_rebuilds_dependent_state_and_restore_reapplies_it(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Skip dependent later commands after exclusion and restore full replay.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope, sources = _prepared_sources(factory, 2)
    repository = DbEvolutionRepository(factory)
    relationship, adaptations = _starting(scope)
    repository.initialize(relationship, adaptations)
    provenance = _provenance()
    first = SetSocialStatusCommand(
        expected=RelationshipSocialStatus.STRANGER,
        value=RelationshipSocialStatus.ACQUAINTANCE,
        rationale="The first turn establishes an acquaintance.",
        sources=(sources[0],),
    )
    second = SetSocialStatusCommand(
        expected=RelationshipSocialStatus.ACQUAINTANCE,
        value=RelationshipSocialStatus.CASUAL_FRIEND,
        rationale="The later turn builds on the acquaintance.",
        sources=(sources[1],),
    )
    first_event, relationship, adaptations = _append(
        repository, sources[0], provenance, first, relationship, adaptations
    )
    _, relationship, adaptations = _append(
        repository, sources[1], provenance, second, relationship, adaptations
    )
    projection_service = EvolutionProjectionService(
        repository, DbContinuityRepository(factory)
    )

    excluded = projection_service.exclude(
        scope,
        first_event.id,
        expected_relationship_revision=2,
        expected_adaptation_revision=0,
        note="These turns did not establish a friendship.",
    )
    assert excluded.relationship.social == RelationshipSocialStatus.STRANGER
    assert excluded.relationship.revision == 3
    assert repository.list_events(scope)[0] == first_event
    assert (
        repository.list_corrections(scope)[0].action
        == EvolutionCorrectionAction.EXCLUDE
    )

    with pytest.raises(EvolutionCorrectionConflictError, match="stale"):
        projection_service.restore(
            scope,
            first_event.id,
            expected_relationship_revision=2,
            expected_adaptation_revision=0,
            note="Stale restoration.",
        )

    restored = projection_service.restore(
        scope,
        first_event.id,
        expected_relationship_revision=3,
        expected_adaptation_revision=0,
        note="Restore the original interpretation.",
    )
    assert restored.relationship.social == RelationshipSocialStatus.CASUAL_FRIEND
    assert restored.relationship.revision == 4


def test_replacement_updates_persona_adaptation_without_editing_inference(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Append a user replacement while retaining the inferred adaptation event.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope, sources = _prepared_sources(factory, 1)
    repository = DbEvolutionRepository(factory)
    relationship, adaptations = _starting(scope)
    repository.initialize(relationship, adaptations)
    inferred = SetPersonaAdaptationCommand(
        facet=AdaptationFacet.COMMUNICATION_STYLE,
        expected=None,
        value="Uses gentle reassurance.",
        rationale="The turn supports a gentle style.",
        sources=(sources[0],),
    )
    inferred_event, relationship, adaptations = _append(
        repository,
        sources[0],
        _provenance(),
        inferred,
        relationship,
        adaptations,
    )
    replacement = inferred.model_copy(
        update={
            "value": "Uses concise humor.",
            "rationale": "The user corrected the preferred communication style.",
        }
    )
    projection_service = EvolutionProjectionService(
        repository, DbContinuityRepository(factory)
    )

    corrected = projection_service.replace(
        scope,
        inferred_event.id,
        replacement,
        expected_relationship_revision=0,
        expected_adaptation_revision=1,
        note="Prefer concise humor to reassurance.",
    )

    assert corrected.persona_adaptations.adaptations == (
        PersonaAdaptation(
            facet=AdaptationFacet.COMMUNICATION_STYLE,
            value="Uses concise humor.",
        ),
    )
    assert corrected.persona_adaptations.revision == 2
    assert repository.list_events(scope)[0].command == inferred
    assert repository.list_corrections(scope)[0].replacement == replacement


def test_deleted_projection_caches_rebuild_to_the_same_state(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Recreate deleted caches exactly from starting state and event history.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope, sources = _prepared_sources(factory, 1)
    repository = DbEvolutionRepository(factory)
    relationship, adaptations = _starting(scope)
    repository.initialize(relationship, adaptations)
    command = SetSocialStatusCommand(
        expected=RelationshipSocialStatus.STRANGER,
        value=RelationshipSocialStatus.ACQUAINTANCE,
        rationale="The turn establishes an acquaintance.",
        sources=(sources[0],),
    )
    event, relationship, adaptations = _append(
        repository,
        sources[0],
        _provenance(),
        command,
        relationship,
        adaptations,
    )
    expected = repository.get_projections(scope)
    with factory() as session, session.begin():
        session.execute(
            delete(PersonaAdaptationProjectionModel).where(
                PersonaAdaptationProjectionModel.continuity_id == scope.continuity_id
            )
        )
        session.execute(
            delete(RelationshipProjectionModel).where(
                RelationshipProjectionModel.continuity_id == scope.continuity_id
            )
        )

    rebuilt = EvolutionProjectionService(
        repository, DbContinuityRepository(factory)
    ).rebuild(scope)

    assert rebuilt.relationship == expected.relationship
    assert rebuilt.persona_adaptations == expected.persona_adaptations
    assert rebuilt.relationship_checkpoint_id == event.id
    assert rebuilt.adaptation_checkpoint_id is None


def _prepared_sources(
    factory: sessionmaker[Session], count: int
) -> tuple[EvolutionScope, tuple[EvolutionEvidenceReference, ...]]:
    """Create completed Ongoing turns and return exact evolution references.

    Args:
        factory:
            Characters database sessions.
        count:
            Number of completed turns to create.

    Returns:
        Complete evolution scope and chronological source references.
    """

    conversation_scope = start(factory)
    app = service(factory, FakeResponse())
    target = ongoing_target(conversation_scope)
    for position in range(count):
        attempt = app.send(
            target, SubmittedInput(content=f"Evolution evidence {position + 1}.")
        )
        list(app.stream(target, attempt.id))
    messages = app.history(target).messages
    scope = EvolutionScope(
        identity_id=conversation_scope.identity_id,
        persona_id=conversation_scope.persona_id,
        continuity_id=conversation_scope.continuity_id,
    )
    sources = tuple(
        EvolutionEvidenceReference(
            scope=scope,
            kind=EvolutionEvidenceKind.ONGOING_TURN,
            conversation_id=conversation_scope.conversation_id,
            user_message_id=messages[index * 2].id,
            user_sequence=index * 2 + 1,
            persona_message_id=messages[index * 2 + 1].id,
            persona_sequence=index * 2 + 2,
        )
        for index in range(count)
    )
    return scope, sources


def _starting(
    scope: EvolutionScope,
) -> tuple[RelationshipProjection, PersonaAdaptationProjection]:
    """Build revision-zero projections matching the test continuity defaults.

    Args:
        scope:
            Complete evolution ownership.

    Returns:
        Starting relationship and empty persona-adaptation projections.
    """

    return (
        RelationshipProjection(
            scope=scope,
            revision=0,
            social=RelationshipSocialStatus.STRANGER,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.NEUTRAL,
            trust=RelationshipTrust.UNKNOWN,
            affection=RelationshipAffection.NEUTRAL,
        ),
        PersonaAdaptationProjection(scope=scope, revision=0),
    )


def _provenance() -> EvolutionProvenance:
    """Build fixed inferred-event provenance for replay tests.

    Returns:
        Complete deterministic strategy provenance.
    """

    return EvolutionProvenance(
        selector=StrategyIdentity(name="test.selector", version="1.0.0"),
        strategy=StrategyIdentity(name="test.strategy", version="1.0.0"),
        policy=StrategyIdentity(name="test.policy", version="1.0.0"),
        schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
    )


def _append(
    repository: DbEvolutionRepository,
    source: EvolutionEvidenceReference,
    provenance: EvolutionProvenance,
    command: EvolutionCommand,
    relationship: RelationshipProjection,
    adaptations: PersonaAdaptationProjection,
) -> tuple[EvolutionEvent, RelationshipProjection, PersonaAdaptationProjection]:
    """Commit one inferred command and its incrementally updated projections.

    Args:
        repository:
            Evolution persistence boundary.
        source:
            Exact completed turn.
        provenance:
            Fixed strategy provenance.
        command:
            Accepted typed change.
        relationship:
            Current relationship cache.
        adaptations:
            Current adaptation cache.

    Returns:
        Persisted event and updated paired projections.
    """

    proposal = EvolutionProposal(
        id=uuid4(),
        scope=source.scope,
        expected_relationship_revision=relationship.revision,
        expected_adaptation_revision=adaptations.revision,
        source=source,
        provenance=provenance,
        commands=(command,),
    )
    adaptation_command = isinstance(command, SetPersonaAdaptationCommand)
    event = EvolutionEvent(
        id=uuid4(),
        proposal_id=proposal.id,
        scope=source.scope,
        command=command,
        relationship_revision=relationship.revision + (not adaptation_command),
        adaptation_revision=adaptations.revision + adaptation_command,
        provenance=provenance,
        created_at=datetime.now(UTC),
    )
    if isinstance(command, SetSocialStatusCommand):
        relationship = relationship.model_copy(
            update={"revision": event.relationship_revision, "social": command.value}
        )
    elif isinstance(command, SetPersonaAdaptationCommand):
        adaptations = adaptations.model_copy(
            update={
                "revision": event.adaptation_revision,
                "adaptations": (
                    PersonaAdaptation(facet=command.facet, value=command.value),
                ),
            }
        )
    decision = EvolutionDecision(
        proposal_id=proposal.id,
        outcome=EvolutionDecisionOutcome.APPLIED,
        events=(event,),
    )
    effect = repository.reserve(source, provenance)
    repository.complete(effect.id, proposal, decision, relationship, adaptations)
    return event, relationship, adaptations
