"""Executable relationship and persona-evolution value tests."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    MAX_EVOLUTION_COMMANDS,
    AdaptationFacet,
    ContinuityMode,
    EvolutionDecision,
    EvolutionDecisionOutcome,
    EvolutionEvent,
    EvolutionEvidence,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionRejectionReason,
    EvolutionScope,
    EvolutionSnapshot,
    Identity,
    IdentityDetails,
    Persona,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    PersonaCore,
    RecordRelationshipMilestoneCommand,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipIntent,
    RelationshipMilestone,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SetDynamicCommand,
    SetPersonaAdaptationCommand,
    SetTrustCommand,
    StrategyIdentity,
)


def _reference(
    scope: EvolutionScope,
    *,
    kind: EvolutionEvidenceKind = EvolutionEvidenceKind.ONGOING_TURN,
    conversation_id: UUID | None = None,
    scene_position: int | None = None,
) -> EvolutionEvidenceReference:
    """Build one exact evidence reference.

    Args:
        scope:
            Owning evolution scope.
        kind:
            Ongoing or Storyline evidence shape.
        conversation_id:
            Optional fixed conversation identifier.
        scene_position:
            Storyline scene position when applicable.

    Returns:
        Valid exact evidence reference.
    """

    return EvolutionEvidenceReference(
        scope=scope,
        kind=kind,
        conversation_id=conversation_id or uuid4(),
        scene_id=(
            uuid4() if kind == EvolutionEvidenceKind.STORYLINE_CHECKPOINT else None
        ),
        scene_position=scene_position,
        user_message_id=uuid4(),
        user_sequence=1,
        persona_message_id=uuid4(),
        persona_sequence=2,
    )


def _provenance() -> EvolutionProvenance:
    """Build complete deterministic provenance.

    Returns:
        Versioned selector, strategy, policy, and schema identities.
    """

    return EvolutionProvenance(
        selector=StrategyIdentity(name="test.selector", version="1.0.0"),
        strategy=StrategyIdentity(name="test.strategy", version="1.0.0"),
        policy=StrategyIdentity(name="test.policy", version="1.0.0"),
        schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
    )


def _snapshot(
    scope: EvolutionScope,
    references: tuple[EvolutionEvidenceReference, ...],
) -> EvolutionSnapshot:
    """Build one snapshot from exact references.

    Args:
        scope:
            Owning evolution scope.
        references:
            Chronological exact evidence references.

    Returns:
        Fully owned immutable evolution snapshot.
    """

    return EvolutionSnapshot(
        scope=scope,
        mode=(
            ContinuityMode.STORYLINE
            if references[0].kind == EvolutionEvidenceKind.STORYLINE_CHECKPOINT
            else ContinuityMode.ONGOING
        ),
        identity=Identity(
            id=scope.identity_id,
            details=IdentityDetails(name="You"),
            is_frozen=True,
            is_default=True,
        ),
        persona=Persona(
            id=scope.persona_id,
            core=PersonaCore(name="Guide", definition="A thoughtful guide"),
            is_frozen=True,
        ),
        relationship_intent=RelationshipIntent.PLATONIC,
        boundaries=("no_romance",),
        relationship=RelationshipProjection(
            scope=scope,
            revision=2,
            social=RelationshipSocialStatus.ACQUAINTANCE,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.NEUTRAL,
            trust=RelationshipTrust.CAUTIOUS,
            affection=RelationshipAffection.WARM,
        ),
        persona_adaptations=PersonaAdaptationProjection(
            scope=scope,
            revision=1,
            adaptations=(
                PersonaAdaptation(
                    facet=AdaptationFacet.SUPPORT_STYLE,
                    value="Offer practical help",
                ),
            ),
        ),
        evidence=tuple(
            EvolutionEvidence(
                reference=reference,
                user_content="I need your help.",
                persona_content="I am here.",
            )
            for reference in references
        ),
        source=references[-1],
    )


def test_storyline_evidence_keeps_scene_and_conversation_checkpoints() -> None:
    """Represent several Storyline conversations under one continuity."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    first = _reference(
        scope, kind=EvolutionEvidenceKind.STORYLINE_CHECKPOINT, scene_position=1
    )
    second = _reference(
        scope, kind=EvolutionEvidenceKind.STORYLINE_CHECKPOINT, scene_position=2
    )
    snapshot = _snapshot(scope, (first, second))
    assert snapshot.evidence[0].reference.conversation_id != (
        snapshot.evidence[1].reference.conversation_id
    )
    assert snapshot.source.scene_position == 2


def test_snapshot_rejects_foreign_duplicate_and_reordered_evidence() -> None:
    """Fail unsafe evidence sets at the immutable snapshot boundary."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    source = _reference(scope)
    values = _snapshot(scope, (source,)).model_dump()
    values["evidence"] = (values["evidence"][0], values["evidence"][0])
    with pytest.raises(ValidationError, match="must be unique"):
        EvolutionSnapshot.model_validate(values)

    foreign_scope = scope.model_copy(update={"continuity_id": uuid4()})
    foreign = _reference(foreign_scope)
    values = _snapshot(scope, (source,)).model_dump()
    values["evidence"] = (
        EvolutionEvidence(
            reference=foreign,
            user_content="Foreign input",
            persona_content="Foreign response",
        ),
    )
    values["source"] = foreign
    with pytest.raises(ValidationError, match="foreign"):
        EvolutionSnapshot.model_validate(values)


def test_exact_enums_and_projection_uniqueness_reject_invalid_state() -> None:
    """Reject free-form relationship values and duplicated adaptation facets."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    with pytest.raises(ValidationError):
        RelationshipProjection.model_validate(
            {
                "scope": scope,
                "revision": 0,
                "social": "best_friend",
                "romantic": "none",
                "dynamic": "neutral",
                "trust": "unknown",
                "affection": "neutral",
            }
        )
    adaptation = PersonaAdaptation(facet=AdaptationFacet.OPENNESS, value="Be candid")
    with pytest.raises(ValidationError, match="must be unique"):
        PersonaAdaptationProjection(
            scope=scope, revision=1, adaptations=(adaptation, adaptation)
        )


def test_commands_reject_duplicate_sources_no_ops_and_bad_milestones() -> None:
    """Reject malformed typed transitions before policy evaluation."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    source = _reference(scope)
    with pytest.raises(ValidationError, match="must be unique"):
        SetTrustCommand(
            expected=RelationshipTrust.UNKNOWN,
            value=RelationshipTrust.CAUTIOUS,
            rationale="Direct evidence",
            sources=(source, source),
        )
    with pytest.raises(ValidationError, match="must change"):
        SetDynamicCommand(
            expected=RelationshipDynamic.NEUTRAL,
            value=RelationshipDynamic.NEUTRAL,
            rationale="No actual transition",
            sources=(source,),
        )
    with pytest.raises(ValidationError, match="invalid resulting status"):
        RecordRelationshipMilestoneCommand(
            milestone=RelationshipMilestone.ENGAGEMENT,
            expected=RelationshipRomanticStatus.PARTNER,
            value=RelationshipRomanticStatus.SPOUSE,
            rationale="Contradictory milestone",
            sources=(source,),
        )


def test_proposal_is_bounded_owned_and_atomic_by_target() -> None:
    """Reject foreign, conflicting, and unbounded atomic proposals."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    source = _reference(scope)
    command = SetPersonaAdaptationCommand(
        facet=AdaptationFacet.OPENNESS,
        value="Be candid",
        rationale="Direct request",
        sources=(source,),
    )
    base = {
        "id": uuid4(),
        "scope": scope,
        "expected_relationship_revision": 2,
        "expected_adaptation_revision": 1,
        "source": source,
        "provenance": _provenance(),
    }
    with pytest.raises(ValidationError, match="targets must be unique"):
        EvolutionProposal.model_validate({**base, "commands": (command, command)})
    with pytest.raises(ValidationError, match="at most 8"):
        EvolutionProposal.model_validate(
            {
                **base,
                "commands": tuple(command for _ in range(MAX_EVOLUTION_COMMANDS + 1)),
            }
        )

    foreign = _reference(scope.model_copy(update={"continuity_id": uuid4()}))
    foreign_command = command.model_copy(update={"sources": (foreign,)})
    with pytest.raises(ValidationError, match="evidence is foreign"):
        EvolutionProposal.model_validate({**base, "commands": (foreign_command,)})


def test_events_and_decisions_enforce_terminal_shapes() -> None:
    """Keep accepted events replayable and terminal decisions unambiguous."""

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    source = _reference(scope)
    proposal_id = uuid4()
    event = EvolutionEvent(
        id=uuid4(),
        proposal_id=proposal_id,
        scope=scope,
        command=SetTrustCommand(
            expected=RelationshipTrust.UNKNOWN,
            value=RelationshipTrust.CAUTIOUS,
            rationale="Direct evidence",
            sources=(source,),
        ),
        relationship_revision=1,
        adaptation_revision=0,
        provenance=_provenance(),
        created_at=datetime.now(UTC),
    )
    applied = EvolutionDecision(
        proposal_id=proposal_id,
        outcome=EvolutionDecisionOutcome.APPLIED,
        events=(event,),
    )
    assert applied.events == (event,)
    rejected = EvolutionDecision(
        proposal_id=proposal_id,
        outcome=EvolutionDecisionOutcome.REJECTED,
        reason=EvolutionRejectionReason.EVIDENCE,
    )
    assert rejected.events == ()
    with pytest.raises(ValidationError, match="requires accepted events"):
        EvolutionDecision(
            proposal_id=proposal_id,
            outcome=EvolutionDecisionOutcome.APPLIED,
        )
