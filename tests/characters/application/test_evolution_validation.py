"""Atomic Characters evolution proposal validation tests."""

from datetime import UTC, datetime
from uuid import uuid4

from chat_buddy.characters.application import (
    EvolutionProposalValidator,
    StrictBaselineEvolutionThresholdPolicy,
)
from chat_buddy.characters.domain import (
    AdaptationFacet,
    Boundary,
    ContinuityMode,
    EvolutionCommand,
    EvolutionDecisionOutcome,
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
    SetPersonaAdaptationCommand,
    SetRomanticStatusCommand,
    SetTrustCommand,
    StrategyIdentity,
)


def _snapshot(
    *,
    turns: tuple[tuple[str, str], ...] = (
        ("I trusted you with something important.", "I will keep it safe."),
        ("You kept my trust.", "That trust matters to me."),
    ),
    intent: RelationshipIntent = RelationshipIntent.NATURAL,
    boundaries: tuple[Boundary, ...] = (),
    persona_definition: str = "A patient and thoughtful guide.",
) -> EvolutionSnapshot:
    """Build a complete snapshot with chronological selected evidence.

    Args:
        turns:
            Exact user and persona exchanges.
        intent:
            User-selected relationship direction.
        boundaries:
            User-controlled constraints.
        persona_definition:
            Immutable authored persona core.

    Returns:
        Fully owned evolution snapshot.
    """

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    conversation_id = uuid4()
    references = tuple(
        EvolutionEvidenceReference(
            scope=scope,
            kind=EvolutionEvidenceKind.ONGOING_TURN,
            conversation_id=conversation_id,
            user_message_id=uuid4(),
            user_sequence=index * 2 - 1,
            persona_message_id=uuid4(),
            persona_sequence=index * 2,
        )
        for index in range(1, len(turns) + 1)
    )
    return EvolutionSnapshot(
        scope=scope,
        mode=ContinuityMode.ONGOING,
        identity=Identity(
            id=scope.identity_id,
            details=IdentityDetails(name="You"),
            is_frozen=True,
            is_default=True,
        ),
        persona=Persona(
            id=scope.persona_id,
            core=PersonaCore(name="Guide", definition=persona_definition),
            is_frozen=True,
        ),
        relationship_intent=intent,
        boundaries=boundaries,
        relationship=RelationshipProjection(
            scope=scope,
            revision=0,
            social=RelationshipSocialStatus.STRANGER,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.NEUTRAL,
            trust=RelationshipTrust.UNKNOWN,
            affection=RelationshipAffection.NEUTRAL,
        ),
        persona_adaptations=PersonaAdaptationProjection(scope=scope, revision=0),
        evidence=tuple(
            EvolutionEvidence(
                reference=reference,
                user_content=turn[0],
                persona_content=turn[1],
            )
            for reference, turn in zip(references, turns, strict=True)
        ),
        source=references[-1],
    )


def _provenance(*, policy: str = "baseline.strict") -> EvolutionProvenance:
    """Build validator-compatible versioned provenance.

    Args:
        policy:
            Recorded threshold-policy name.

    Returns:
        Complete strategy and validation provenance.
    """

    return EvolutionProvenance(
        selector=StrategyIdentity(name="test.selector", version="1.0.0"),
        strategy=StrategyIdentity(name="test.strategy", version="1.0.0"),
        policy=StrategyIdentity(name=policy, version="1.0.0"),
        schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
    )


def _proposal(
    snapshot: EvolutionSnapshot, commands: tuple[EvolutionCommand, ...]
) -> EvolutionProposal:
    """Build a proposal and validate its typed commands.

    Args:
        snapshot:
            Expected current state.
        commands:
            Typed commands accepted by the proposal model.

    Returns:
        Complete atomic proposal.
    """

    return EvolutionProposal.model_validate(
        {
            "id": uuid4(),
            "scope": snapshot.scope,
            "expected_relationship_revision": snapshot.relationship.revision,
            "expected_adaptation_revision": snapshot.persona_adaptations.revision,
            "source": snapshot.source,
            "provenance": _provenance(),
            "commands": commands,
        }
    )


def _validator() -> EvolutionProposalValidator:
    """Build the strict baseline validator with a fixed aware clock.

    Returns:
        Deterministic production validator.
    """

    return EvolutionProposalValidator(
        StrictBaselineEvolutionThresholdPolicy(),
        clock=lambda: datetime(2026, 10, 29, tzinfo=UTC),
    )


def test_validator_applies_all_commands_atomically_with_traceable_events() -> None:
    """Apply valid relationship and adaptation changes as one change set."""

    snapshot = _snapshot()
    trust = SetTrustCommand(
        expected=RelationshipTrust.UNKNOWN,
        value=RelationshipTrust.TRUSTING,
        rationale="Two exchanges establish trust.",
        sources=tuple(item.reference for item in snapshot.evidence),
    )
    adaptation = SetPersonaAdaptationCommand(
        facet=AdaptationFacet.OPENNESS,
        value="Respond more candidly",
        rationale="The latest exchange supports candid communication.",
        sources=(snapshot.source,),
    )
    proposal = _proposal(snapshot, (trust, adaptation))

    result = _validator().evaluate(snapshot, proposal)

    assert result.decision.outcome == EvolutionDecisionOutcome.APPLIED
    assert tuple(event.command for event in result.decision.events) == proposal.commands
    assert result.relationship.revision == 1
    assert result.relationship.trust == RelationshipTrust.TRUSTING
    assert result.persona_adaptations.revision == 1
    assert result.persona_adaptations.adaptations[0].value == "Respond more candidly"


def test_validator_records_empty_proposals_as_no_change() -> None:
    """Return unchanged projections for a well-formed empty proposal."""

    snapshot = _snapshot()
    result = _validator().evaluate(snapshot, _proposal(snapshot, ()))

    assert result.decision.outcome == EvolutionDecisionOutcome.NO_CHANGE
    assert result.relationship == snapshot.relationship
    assert result.persona_adaptations == snapshot.persona_adaptations


def test_validator_uses_deterministic_rejection_precedence() -> None:
    """Expose every stable validator category without partial application."""

    snapshot = _snapshot()
    trust = SetTrustCommand(
        expected=RelationshipTrust.UNKNOWN,
        value=RelationshipTrust.CAUTIOUS,
        rationale="Trust changes cautiously.",
        sources=tuple(item.reference for item in snapshot.evidence),
    )
    valid = _proposal(snapshot, (trust,))
    cases = (
        (
            valid.model_copy(
                update={"provenance": _provenance(policy="test.other_policy")}
            ),
            EvolutionRejectionReason.OWNERSHIP,
        ),
        (
            valid.model_copy(update={"commands": (trust, trust)}),
            EvolutionRejectionReason.PROPOSAL_BOUNDS,
        ),
        (
            valid.model_copy(update={"expected_relationship_revision": 99}),
            EvolutionRejectionReason.EXPECTED_PROJECTION,
        ),
        (
            _proposal(
                snapshot,
                (
                    trust.model_copy(
                        update={"sources": (snapshot.evidence[0].reference,)}
                    ),
                ),
            ),
            EvolutionRejectionReason.EVIDENCE,
        ),
    )

    for proposal, expected in cases:
        result = _validator().evaluate(snapshot, proposal)
        assert result.decision.reason == expected
        assert result.relationship == snapshot.relationship


def test_validator_rejects_boundary_intent_transition_and_threshold_failures() -> None:
    """Keep romance, transition graphs, and gradual evidence conservative."""

    romantic_turn = (("I feel romantically attracted to you.", "I feel it too."),)
    boundary_snapshot = _snapshot(
        turns=romantic_turn,
        intent=RelationshipIntent.PLATONIC,
        boundaries=("no_romance",),
    )
    romance = SetRomanticStatusCommand(
        expected=RelationshipRomanticStatus.NONE,
        value=RelationshipRomanticStatus.INTEREST,
        rationale="The exchange is explicitly romantic.",
        sources=(boundary_snapshot.source,),
    )
    assert (
        _validator()
        .evaluate(boundary_snapshot, _proposal(boundary_snapshot, (romance,)))
        .decision.reason
        == EvolutionRejectionReason.USER_BOUNDARY
    )

    intent_snapshot = _snapshot(turns=romantic_turn, intent=RelationshipIntent.PLATONIC)
    intent_romance = romance.model_copy(update={"sources": (intent_snapshot.source,)})
    assert (
        _validator()
        .evaluate(intent_snapshot, _proposal(intent_snapshot, (intent_romance,)))
        .decision.reason
        == EvolutionRejectionReason.RELATIONSHIP_INTENT
    )

    milestone_snapshot = _snapshot(
        turns=(("Maybe someday this could be forever.", "Maybe it could."),),
        intent=RelationshipIntent.OPEN_TO_ROMANCE,
    )
    milestone_snapshot = milestone_snapshot.model_copy(
        update={
            "relationship": milestone_snapshot.relationship.model_copy(
                update={"romantic": RelationshipRomanticStatus.DATING}
            )
        }
    )
    milestone = RecordRelationshipMilestoneCommand(
        milestone=RelationshipMilestone.ENGAGEMENT,
        expected=RelationshipRomanticStatus.DATING,
        value=RelationshipRomanticStatus.ENGAGED,
        rationale="A vague possibility cannot establish engagement.",
        sources=(milestone_snapshot.source,),
    )
    assert (
        _validator()
        .evaluate(milestone_snapshot, _proposal(milestone_snapshot, (milestone,)))
        .decision.reason
        == EvolutionRejectionReason.TRANSITION
    )

    threshold_snapshot = _snapshot(turns=(romantic_turn[0],))
    threshold = SetTrustCommand(
        expected=RelationshipTrust.UNKNOWN,
        value=RelationshipTrust.CAUTIOUS,
        rationale="One turn is insufficient for gradual trust.",
        sources=(threshold_snapshot.source,),
    )
    assert (
        _validator()
        .evaluate(threshold_snapshot, _proposal(threshold_snapshot, (threshold,)))
        .decision.reason
        == EvolutionRejectionReason.THRESHOLD
    )


def test_validator_rejects_core_contradictions_and_factual_adaptations() -> None:
    """Keep immutable persona constraints and declarative memory out of adaptation."""

    core_snapshot = _snapshot(
        turns=(("Tease me about fear.", "I will support you without mockery."),),
        persona_definition="A patient guide who never mocks vulnerability.",
    )
    contradiction = SetPersonaAdaptationCommand(
        facet=AdaptationFacet.SUPPORT_STYLE,
        value="Mock fear and vulnerability",
        rationale="The user requested it.",
        sources=(core_snapshot.source,),
    )
    assert (
        _validator()
        .evaluate(core_snapshot, _proposal(core_snapshot, (contradiction,)))
        .decision.reason
        == EvolutionRejectionReason.PERSONA_CORE
    )

    fact_snapshot = _snapshot(turns=(("I moved to Lisbon.", "I will remember that."),))
    factual = SetPersonaAdaptationCommand(
        facet=AdaptationFacet.SHARED_HABIT,
        value="User lives in Lisbon",
        rationale="This is declarative knowledge.",
        sources=(fact_snapshot.source,),
    )
    assert (
        _validator()
        .evaluate(fact_snapshot, _proposal(fact_snapshot, (factual,)))
        .decision.reason
        == EvolutionRejectionReason.ADAPTATION_FACET
    )
