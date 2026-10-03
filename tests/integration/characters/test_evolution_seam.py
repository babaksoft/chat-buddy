"""Evolution substitution and deliberate non-persistence integration coverage."""

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    EvolutionEvaluator,
)
from chat_buddy.characters.domain import CompletedTurn, SubmittedInput
from chat_buddy.characters.domain.evolution import (
    EvolutionEvidenceReference,
    EvolutionInputs,
    EvolutionProposal,
    EvolutionStrategyId,
    RelationshipChangeProposal,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)
from tests.characters_support import FakeResponse, service, start


class RecordingEvolutionStrategy:
    """Test strategy containing no SDK, persistence, or Chat dependencies."""

    def __init__(self) -> None:
        """Initialize stable provenance and an invocation count."""

        self.strategy_id = EvolutionStrategyId(name="test.integration", version="1.0.0")
        self.calls = 0

    def propose(self, inputs: EvolutionInputs) -> EvolutionProposal:
        """Return one traceable detached relationship proposal.

        Args:
            inputs:
                Real Characters snapshots and committed evidence.

        Returns:
            Detached test proposal.
        """

        self.calls += 1
        turn = inputs.evidence[-1]
        return EvolutionProposal(
            strategy=self.strategy_id,
            scope=inputs.scope,
            relationship_changes=(
                RelationshipChangeProposal(
                    dimension="trust",
                    proposed_value="trusting",
                    rationale="The completed exchange supports a future review.",
                    sources=(
                        EvolutionEvidenceReference(
                            user_message_id=turn.user.id,
                            persona_message_id=turn.persona.id,
                        ),
                    ),
                ),
            ),
        )


def test_strategy_substitution_cannot_mutate_production_ongoing_state(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep proposals detached and omit automatic evolution from completed turns.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    continuities = DbContinuityRepository(factory)
    original_identity = identities.get(scope.identity_id)
    original_persona = personas.get(scope.persona_id)
    original_continuity = continuities.get(
        scope.identity_id, scope.persona_id, scope.continuity_id
    )

    strategy = RecordingEvolutionStrategy()
    app = service(factory, FakeResponse())
    attempt = app.send(scope, SubmittedInput(content="I trust your judgment."))
    list(app.stream(scope, attempt.id))
    assert strategy.calls == 0

    history = app.history(scope)
    proposal = EvolutionEvaluator(strategy).evaluate(
        EvolutionInputs(
            scope=scope,
            mode=original_continuity.mode,
            identity=original_identity,
            persona=original_persona,
            starting_relationship=original_continuity.relationship,
            evidence=(
                CompletedTurn(user=history.messages[0], persona=history.messages[1]),
            ),
        )
    )
    assert strategy.calls == 1
    assert proposal.relationship_changes[0].proposed_value == "trusting"
    assert identities.get(scope.identity_id) == original_identity
    assert personas.get(scope.persona_id) == original_persona
    assert (
        continuities.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        ).relationship
        == original_continuity.relationship
    )
