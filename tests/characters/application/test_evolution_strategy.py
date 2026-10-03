"""Versioned, immutable, and scoped evolution strategy contract tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.application import (
    EvolutionEvaluator,
    NoChangeEvolutionStrategy,
)
from chat_buddy.characters.domain import (
    CompletedTurn,
    ContinuityMode,
    ConversationScope,
    EvolutionEvidenceReference,
    EvolutionInputs,
    EvolutionProposal,
    EvolutionStrategyId,
    Identity,
    IdentityDetails,
    Message,
    Persona,
    PersonaAdaptationProposal,
    PersonaCore,
    RelationshipChangeProposal,
    RelationshipIntent,
    StartingOrigins,
    StartingRelationship,
)


def _inputs() -> EvolutionInputs:
    """Build one complete immutable evolution input.

    Returns:
        Scoped profile snapshots and one eligible complete turn.
    """

    scope = ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )
    now = datetime.now(UTC)
    user_message = Message(
        id=uuid4(),
        scope=scope,
        sequence=1,
        role="user",
        content="I trust you.",
        created_at=now,
    )
    persona_message = Message(
        id=uuid4(),
        scope=scope,
        sequence=2,
        role="persona",
        content="I appreciate that.",
        created_at=now,
    )

    return EvolutionInputs(
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
        starting_relationship=StartingRelationship(
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
        ),
        evidence=(CompletedTurn(user=user_message, persona=persona_message),),
    )


class TestEvolutionStrategy:
    """Test-only implementation proving structural strategy substitution."""

    __test__ = False

    def __init__(self) -> None:
        """Initialize stable test provenance and input capture."""

        self.strategy_id = EvolutionStrategyId(
            name="test.relationship", version="2.1.0"
        )
        self.seen: EvolutionInputs | None = None

    def propose(self, inputs: EvolutionInputs) -> EvolutionProposal:
        """Propose two traceable changes using only domain values.

        Args:
            inputs:
                Immutable snapshots and evidence.

        Returns:
            Detached structured proposal.
        """

        self.seen = inputs
        turn = inputs.evidence[0]
        source = EvolutionEvidenceReference(
            user_message_id=turn.user.id,
            persona_message_id=turn.persona.id,
        )

        return EvolutionProposal(
            strategy=self.strategy_id,
            scope=inputs.scope,
            persona_adaptations=(
                PersonaAdaptationProposal(
                    facet="openness",
                    proposed_value="more candid",
                    rationale="The user explicitly offered trust.",
                    sources=(source,),
                ),
            ),
            relationship_changes=(
                RelationshipChangeProposal(
                    dimension="trust",
                    proposed_value="trusting",
                    rationale="The exchange supplies direct trust evidence.",
                    sources=(source,),
                ),
            ),
        )


def test_strategy_identity_inputs_and_outputs_are_frozen_and_versioned() -> None:
    """Require immutable snapshots and semantic strategy provenance."""

    inputs = _inputs()
    result = EvolutionEvaluator(TestEvolutionStrategy()).evaluate(inputs)
    assert result.strategy == EvolutionStrategyId(
        name="test.relationship", version="2.1.0"
    )
    assert result.scope == inputs.scope
    assert result.relationship_changes[0].sources[0].user_message_id == (
        inputs.evidence[0].user.id
    )
    with pytest.raises(ValidationError):
        inputs.mode = ContinuityMode.TIMELINE
    with pytest.raises(ValidationError):
        result.relationship_changes = ()
    with pytest.raises(ValidationError):
        EvolutionStrategyId(name="Display Name", version="latest")


def test_inputs_reject_foreign_or_non_chronological_evidence() -> None:
    """Keep all strategy evidence within one ordered conversation scope."""

    inputs = _inputs()
    foreign_scope = inputs.scope.model_copy(update={"continuity_id": uuid4()})
    foreign_user = inputs.evidence[0].user.model_copy(update={"scope": foreign_scope})
    foreign_persona = inputs.evidence[0].persona.model_copy(
        update={"scope": foreign_scope}
    )
    values = inputs.model_dump()
    values["evidence"] = (CompletedTurn(user=foreign_user, persona=foreign_persona),)
    with pytest.raises(ValidationError, match="supplied scope"):
        EvolutionInputs.model_validate(values)


def test_baseline_is_stable_and_explicitly_proposes_no_changes() -> None:
    """Return a versioned empty result without consulting external components."""

    inputs = _inputs()
    strategy = NoChangeEvolutionStrategy()
    result = EvolutionEvaluator(strategy).evaluate(inputs)
    assert strategy.strategy_id == EvolutionStrategyId(
        name="baseline.no_change", version="1.0.0"
    )
    assert result.persona_adaptations == ()
    assert result.relationship_changes == ()


def test_evaluator_rejects_untraceable_strategy_output() -> None:
    """Reject a proposal that cites a turn outside its eligible input."""

    class ForeignEvidenceStrategy(TestEvolutionStrategy):
        """Return one otherwise valid proposal with fabricated sources."""

        def propose(self, inputs: EvolutionInputs) -> EvolutionProposal:
            """Replace the valid proposal source with foreign identifiers.

            Args:
                inputs:
                    Immutable Characters inputs.

            Returns:
                Proposal containing an ineligible source.
            """

            result = super().propose(inputs)
            change = result.relationship_changes[0].model_copy(
                update={
                    "sources": (
                        EvolutionEvidenceReference(
                            user_message_id=uuid4(), persona_message_id=uuid4()
                        ),
                    )
                }
            )
            return result.model_copy(update={"relationship_changes": (change,)})

    with pytest.raises(ValueError, match="ineligible evidence"):
        EvolutionEvaluator(ForeignEvidenceStrategy()).evaluate(_inputs())
