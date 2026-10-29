"""Bounded evolution snapshot integration coverage."""

from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import BaselineEvolutionSnapshotSelector
from chat_buddy.characters.domain import (
    CreateMemoryCommand,
    EvolutionEvidenceKind,
    EvolutionEvidenceReference,
    EvolutionScope,
    EvolutionSnapshotBudget,
    MemoryDelta,
    PersonaAdaptationProjection,
    PromptMessage,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SceneAppendEligibility,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbEvolutionRepository,
    DbIdentityRepository,
    DbMemoryExtractionRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineMemoryRepository,
    DbStorylineRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import Utf8TokenCounter
from tests.characters_support import FakeResponse, ongoing_target, service, start
from tests.integration.characters.test_storyline_memory_repositories import (
    _evidence,
    _provenance,
)
from tests.integration.characters.test_storyline_repositories import (
    _complete_exchange,
    _next_scene,
    _relationship,
    _repositories_and_request,
)


class MessageCountTokenCounter:
    """Count one token per rendered immutable snapshot block."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Return the number of complete rendered blocks.

        Args:
            messages:
                Complete candidate snapshot rendering.

        Returns:
            Number of whole blocks.
        """

        return len(messages)


def test_ongoing_snapshot_uses_only_the_selected_retry(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Exclude an unselected retry sibling from exact Ongoing evidence.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    conversation_scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    initial = app.send(
        ongoing_target(conversation_scope), SubmittedInput(content="Question")
    )
    list(app.stream(ongoing_target(conversation_scope), initial.id))
    original_persona_id = (
        app.history(ongoing_target(conversation_scope)).messages[-1].id
    )
    gateway.chunks = ("Selected alternative",)
    retry = app.retry_completed_response(ongoing_target(conversation_scope))
    list(app.stream(ongoing_target(conversation_scope), retry.id))
    history = app.history(ongoing_target(conversation_scope))
    selected_persona = history.messages[-1]
    scope = EvolutionScope(
        identity_id=conversation_scope.identity_id,
        persona_id=conversation_scope.persona_id,
        continuity_id=conversation_scope.continuity_id,
    )
    source = EvolutionEvidenceReference(
        scope=scope,
        kind=EvolutionEvidenceKind.ONGOING_TURN,
        conversation_id=conversation_scope.conversation_id,
        user_message_id=history.messages[-2].id,
        user_sequence=1,
        persona_message_id=selected_persona.id,
        persona_sequence=2,
    )
    evolution = DbEvolutionRepository(factory)
    evolution.initialize(
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

    snapshot = _selector(factory, evolution).select(scope, source)

    assert tuple(item.persona_content for item in snapshot.evidence) == (
        "Selected alternative",
    )
    assert original_persona_id not in {
        item.reference.persona_message_id for item in snapshot.evidence
    }
    assert snapshot.memories == ()


def test_storyline_snapshot_is_deterministic_bounded_and_cross_scene_safe(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Select exact chronological turns across Storyline conversations.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, scenes, request = _repositories_and_request(factory)
    storyline, first_scene = storylines.start(request, _relationship())
    first_leaf = _complete_exchange(
        factory, first_scene.scope.conversation_id, storyline.id
    )
    first_path = DbConversationRepository(factory).selected_path(first_scene.scope)
    extraction_provenance = _provenance()
    extraction = DbMemoryExtractionRepository(factory)
    reserved = extraction.reserve(first_scene.scope, first_scene.id, first_leaf)
    memory_evidence = _evidence(
        first_scene.scope,
        first_scene.id,
        first_path.messages[0].id,
        first_leaf,
        2,
        extraction_provenance,
    )
    extraction.apply(
        reserved.id,
        MemoryDelta(
            selection_id=uuid4(),
            scope=first_scene.scope,
            source_persona_message_id=first_leaf,
            extractor=extraction_provenance.extractor,
            commands=(
                CreateMemoryCommand(
                    subject="departure time",
                    content="The train leaves at midnight.",
                    occurrence=memory_evidence.occurrence,
                    evidence=memory_evidence,
                ),
            ),
        ),
        extraction_provenance,
    )
    sequence = scenes.append_next(
        _next_scene(),
        SceneAppendEligibility(
            storyline_id=storyline.id,
            scene_id=first_scene.id,
            expected_storyline_revision=storyline.revision,
            expected_selected_leaf_id=first_leaf,
            scene_position=first_scene.position,
            storyline_lifecycle=storyline.lifecycle,
            is_latest_scene=True,
            has_complete_selected_exchange=True,
            has_unmatched_input=False,
            has_open_attempt=False,
        ),
    )
    second_scene = sequence.scenes[-1]
    second_leaf = _complete_exchange(
        factory, second_scene.scope.conversation_id, storyline.id
    )
    second_path = DbConversationRepository(factory).selected_path(second_scene.scope)
    source = EvolutionEvidenceReference(
        scope=EvolutionScope(
            identity_id=storyline.identity_id,
            persona_id=storyline.persona_id,
            continuity_id=storyline.id,
        ),
        kind=EvolutionEvidenceKind.STORYLINE_CHECKPOINT,
        conversation_id=second_scene.scope.conversation_id,
        scene_id=second_scene.id,
        scene_position=second_scene.position,
        user_message_id=second_path.messages[0].id,
        user_sequence=1,
        persona_message_id=second_leaf,
        persona_sequence=2,
    )
    evolution = DbEvolutionRepository(factory)
    evolution.initialize(
        RelationshipProjection(
            scope=source.scope,
            revision=0,
            social=RelationshipSocialStatus.STRANGER,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.NEUTRAL,
            trust=RelationshipTrust.UNKNOWN,
            affection=RelationshipAffection.NEUTRAL,
        ),
        PersonaAdaptationProjection(scope=source.scope, revision=0),
    )
    selector = _selector(factory, evolution)

    first = selector.select(source.scope, source)
    second = selector.select(source.scope, source)

    assert first == second
    assert first.token_count is not None
    assert first.budget is not None
    assert first.token_count <= first.budget.input_tokens
    assert tuple(item.reference.scene_position for item in first.evidence) == (1, 2)
    assert first.source == source
    assert first.evidence[-1].reference.persona_message_id == second_leaf
    assert first.memories[0].sources == (first.evidence[0].reference,)
    assert selector.selector_id.name == "baseline.exact_evidence"

    mandatory_only = _selector(
        factory,
        evolution,
        counter=MessageCountTokenCounter(),
        budget=EvolutionSnapshotBudget(input_tokens=7),
    ).select(source.scope, source)
    assert tuple(item.reference.scene_position for item in mandatory_only.evidence) == (
        2,
    )
    assert mandatory_only.token_count == 7
    assert mandatory_only.memories == ()


def _selector(
    factory: sessionmaker[Session],
    evolution: DbEvolutionRepository,
    counter: Utf8TokenCounter | MessageCountTokenCounter | None = None,
    budget: EvolutionSnapshotBudget | None = None,
) -> BaselineEvolutionSnapshotSelector:
    """Compose the real snapshot selector with a generous deterministic budget.

    Args:
        factory:
            Isolated Characters database factory.
        evolution:
            Initialized current-projection repository.
        counter:
            Optional deterministic token counter override.
        budget:
            Optional dedicated capacity override.

    Returns:
        Fully composed baseline selector.
    """

    return BaselineEvolutionSnapshotSelector(
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbContinuityRepository(factory),
        DbStorylineRepository(factory),
        DbSceneRepository(factory),
        DbConversationRepository(factory),
        DbSummaryRepository(factory),
        DbStorylineMemoryRepository(factory),
        evolution,
        counter or Utf8TokenCounter(),
        budget
        or EvolutionSnapshotBudget(input_tokens=200_000, fixed_overhead_tokens=64),
    )
