"""Versioned, immutable, and scoped evolution strategy contract tests."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.application import (
    EvolutionEvaluator,
    NoChangeEvolutionStrategy,
)
from chat_buddy.characters.domain import (
    AdaptationFacet,
    ContinuityMode,
    EvolutionEvidence,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionScope,
    EvolutionSnapshot,
    Identity,
    IdentityDetails,
    Persona,
    PersonaAdaptationProjection,
    PersonaCore,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipIntent,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SetPersonaAdaptationCommand,
    SetTrustCommand,
    StrategyIdentity,
)


def _provenance(strategy: StrategyIdentity) -> EvolutionProvenance:
    """Build complete versioned test provenance.

    Args:
        strategy:
            Strategy identity to record.

    Returns:
        Complete local test provenance.
    """

    return EvolutionProvenance(
        selector=StrategyIdentity(name="test.selector", version="1.0.0"),
        strategy=strategy,
        policy=StrategyIdentity(name="test.policy", version="1.0.0"),
        schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
    )


def _snapshot() -> EvolutionSnapshot:
    """Build one complete immutable Ongoing snapshot.

    Returns:
        Scoped state and one eligible exact evidence turn.
    """

    scope = EvolutionScope(
        identity_id=uuid4(), persona_id=uuid4(), continuity_id=uuid4()
    )
    reference = EvolutionEvidenceReference(
        scope=scope,
        kind=EvolutionEvidenceKind.ONGOING_TURN,
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        user_sequence=1,
        persona_message_id=uuid4(),
        persona_sequence=2,
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
            core=PersonaCore(name="Guide", definition="A thoughtful guide"),
            is_frozen=True,
        ),
        relationship_intent=RelationshipIntent.PLATONIC,
        boundaries=(),
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
        evidence=(
            EvolutionEvidence(
                reference=reference,
                user_content="I trust you.",
                persona_content="I appreciate that.",
            ),
        ),
        source=reference,
    )


class TestEvolutionStrategy:
    """Test-only implementation proving structural strategy substitution."""

    __test__ = False

    def __init__(self) -> None:
        """Initialize stable test provenance and input capture."""

        self.strategy_id = StrategyIdentity(name="test.relationship", version="2.1.0")
        self.seen: EvolutionSnapshot | None = None

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Propose two traceable typed changes.

        Args:
            snapshot:
                Immutable state and evidence.

        Returns:
            Detached bounded proposal.
        """

        self.seen = snapshot
        return EvolutionProposal(
            id=uuid4(),
            scope=snapshot.scope,
            expected_relationship_revision=snapshot.relationship.revision,
            expected_adaptation_revision=snapshot.persona_adaptations.revision,
            source=snapshot.source,
            provenance=_provenance(self.strategy_id),
            commands=(
                SetPersonaAdaptationCommand(
                    facet=AdaptationFacet.OPENNESS,
                    value="more candid",
                    rationale="The identity explicitly offered trust.",
                    sources=(snapshot.source,),
                ),
                SetTrustCommand(
                    expected=RelationshipTrust.UNKNOWN,
                    value=RelationshipTrust.CAUTIOUS,
                    rationale="The exchange supplies direct trust evidence.",
                    sources=(snapshot.source,),
                ),
            ),
        )


def test_strategy_inputs_and_outputs_are_frozen_typed_and_versioned() -> None:
    """Require immutable snapshots, typed commands, and semantic provenance."""

    snapshot = _snapshot()
    result = EvolutionEvaluator(TestEvolutionStrategy()).evaluate(snapshot)
    assert result.provenance.strategy == StrategyIdentity(
        name="test.relationship", version="2.1.0"
    )
    assert result.scope == snapshot.scope
    assert result.commands[1].sources == (snapshot.source,)
    with pytest.raises(ValidationError):
        snapshot.boundaries = ()
    with pytest.raises(ValidationError):
        result.commands = ()
    with pytest.raises(ValidationError):
        StrategyIdentity(name="Display Name", version="latest")


def test_baseline_is_stable_and_explicitly_proposes_no_changes() -> None:
    """Return a versioned empty result without external components."""

    snapshot = _snapshot()
    strategy = NoChangeEvolutionStrategy()
    result = EvolutionEvaluator(strategy).evaluate(snapshot)
    assert strategy.strategy_id == StrategyIdentity(
        name="baseline.no_change", version="1.0.0"
    )
    assert result.commands == ()
    assert result.source == snapshot.source


def test_evaluator_rejects_untraceable_strategy_output() -> None:
    """Reject a proposal that cites a checkpoint outside its snapshot."""

    class ForeignEvidenceStrategy(TestEvolutionStrategy):
        """Return one otherwise valid proposal with fabricated evidence."""

        def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
            """Replace a command source with an ineligible same-owner reference.

            Args:
                snapshot:
                    Immutable Characters snapshot.

            Returns:
                Proposal containing an ineligible source.
            """

            result = super().propose(snapshot)
            source = snapshot.source.model_copy(
                update={"user_message_id": uuid4(), "persona_message_id": uuid4()}
            )
            command = result.commands[1].model_copy(update={"sources": (source,)})
            return result.model_copy(update={"commands": (result.commands[0], command)})

    with pytest.raises(ValueError, match="ineligible evidence"):
        EvolutionEvaluator(ForeignEvidenceStrategy()).evaluate(_snapshot())


def test_evaluator_rejects_stale_projection_revision() -> None:
    """Reject output based on a different projection revision."""

    class StaleStrategy(TestEvolutionStrategy):
        """Return a proposal carrying stale optimistic state."""

        def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
            """Alter the expected relationship revision.

            Args:
                snapshot:
                    Immutable Characters snapshot.

            Returns:
                Proposal containing a stale revision.
            """

            result = super().propose(snapshot)
            return result.model_copy(update={"expected_relationship_revision": 99})

    with pytest.raises(ValueError, match="revision is stale"):
        EvolutionEvaluator(StaleStrategy()).evaluate(_snapshot())
