"""Evolution substitution and deliberate non-persistence integration coverage."""

from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    EvolutionEvaluator,
)
from chat_buddy.characters.domain import (
    EvolutionEvidence,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionProposal,
    EvolutionProvenance,
    EvolutionScope,
    EvolutionSnapshot,
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
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)
from tests.characters_support import FakeResponse, ongoing_target, service, start


class RecordingEvolutionStrategy:
    """Test strategy containing no SDK, persistence, or Chat dependencies."""

    def __init__(self) -> None:
        """Initialize stable provenance and an invocation count."""

        self.strategy_id = StrategyIdentity(name="test.integration", version="1.0.0")
        self.calls = 0

    def propose(self, snapshot: EvolutionSnapshot) -> EvolutionProposal:
        """Return one traceable detached relationship proposal.

        Args:
            snapshot:
                Real Characters snapshots and committed evidence.

        Returns:
            Detached test proposal.
        """

        self.calls += 1
        return EvolutionProposal(
            id=uuid4(),
            scope=snapshot.scope,
            expected_relationship_revision=snapshot.relationship.revision,
            expected_adaptation_revision=snapshot.persona_adaptations.revision,
            source=snapshot.source,
            provenance=EvolutionProvenance(
                selector=StrategyIdentity(name="test.selector", version="1.0.0"),
                strategy=self.strategy_id,
                policy=StrategyIdentity(name="test.policy", version="1.0.0"),
                schema_identity=StrategyIdentity(name="test.schema", version="1.0.0"),
            ),
            commands=(
                SetTrustCommand(
                    expected=snapshot.relationship.trust,
                    value=RelationshipTrust.TRUSTING,
                    rationale="The completed exchange supports a future review.",
                    sources=(snapshot.source,),
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
    attempt = app.send(
        ongoing_target(scope), SubmittedInput(content="I trust your judgment.")
    )
    list(app.stream(ongoing_target(scope), attempt.id))
    assert strategy.calls == 0

    history = app.history(ongoing_target(scope))
    evolution_scope = EvolutionScope(
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        continuity_id=scope.continuity_id,
    )
    source = EvolutionEvidenceReference(
        scope=evolution_scope,
        kind=EvolutionEvidenceKind.ONGOING_TURN,
        conversation_id=scope.conversation_id,
        user_message_id=history.messages[0].id,
        user_sequence=history.messages[0].sequence,
        persona_message_id=history.messages[1].id,
        persona_sequence=history.messages[1].sequence,
    )
    proposal = EvolutionEvaluator(strategy).evaluate(
        EvolutionSnapshot(
            scope=evolution_scope,
            mode=original_continuity.mode,
            identity=original_identity,
            persona=original_persona,
            relationship_intent=original_continuity.relationship.intent,
            boundaries=original_continuity.relationship.boundaries,
            relationship=RelationshipProjection(
                scope=evolution_scope,
                revision=0,
                social=RelationshipSocialStatus(
                    original_continuity.relationship.social
                ),
                romantic=RelationshipRomanticStatus(
                    original_continuity.relationship.romantic
                ),
                dynamic=RelationshipDynamic(original_continuity.relationship.dynamic),
                trust=RelationshipTrust(original_continuity.relationship.trust),
                affection=RelationshipAffection(
                    original_continuity.relationship.affection
                ),
            ),
            persona_adaptations=PersonaAdaptationProjection(
                scope=evolution_scope, revision=0
            ),
            evidence=(
                EvolutionEvidence(
                    reference=source,
                    user_content=history.messages[0].content,
                    persona_content=history.messages[1].content,
                ),
            ),
            source=source,
        )
    )
    assert strategy.calls == 1
    assert isinstance(proposal.commands[0], SetTrustCommand)
    assert proposal.commands[0].value == "trusting"
    assert identities.get(scope.identity_id) == original_identity
    assert personas.get(scope.persona_id) == original_persona
    assert (
        continuities.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        ).relationship
        == original_continuity.relationship
    )
