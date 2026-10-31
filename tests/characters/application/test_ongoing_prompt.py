"""Characters mandatory block ordering and deterministic capacity boundaries."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ConversationService,
    OngoingContextEligibility,
)
from chat_buddy.characters.domain import (
    AdaptationFacet,
    ContextCapacityError,
    ConversationHistory,
    EffectiveGeneration,
    EvolutionProjectionState,
    EvolutionRepository,
    EvolutionScope,
    GenerationConfiguration,
    Message,
    ModelDescriptor,
    PersonaAdaptation,
    PersonaAdaptationProjection,
    PromptMessage,
    RelationshipAffection,
    RelationshipDynamic,
    RelationshipProjection,
    RelationshipRomanticStatus,
    RelationshipSocialStatus,
    RelationshipTrust,
    SubmittedInput,
    SummaryRevision,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import ConfiguredModelRegistry
from chat_buddy.characters.prompts import assemble_ongoing_prompt
from tests.characters_support import FakeResponse, ongoing_target, registry, start


class FixedCounter:
    """Return an exact token count for capacity boundary tests."""

    def __init__(self, tokens: int) -> None:
        """Capture the scripted count.

        Args:
            tokens:
                Deterministic prompt count.
        """

        self.tokens = tokens

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Report the scripted exact count.

        Args:
            messages:
                Complete provider input.

        Returns:
            Scripted token count.
        """

        return self.tokens


class RecordingCounter:
    """Capture every complete prompt while returning a small estimate."""

    def __init__(self) -> None:
        """Initialize an empty prompt history."""

        self.prompts: list[tuple[PromptMessage, ...]] = []

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Capture a prompt and return its provider-message count.

        Args:
            messages:
                Complete prompt candidate.

        Returns:
            Number of provider messages.
        """

        self.prompts.append(messages)
        return len(messages)


def test_prompt_preserves_required_order_and_relationship_without_synthetic_history(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Render persona, identity, starting relationship, presentation, and history.

    Args:
        characters_session_factory:
            Isolated Characters repositories providing immutable snapshots.
    """

    factory = characters_session_factory
    scope = start(factory)
    persona = DbPersonaRepository(factory).get(scope.persona_id)
    identity = DbIdentityRepository(factory).get(scope.identity_id)
    continuity = DbContinuityRepository(factory).get(
        scope.identity_id, scope.persona_id, scope.continuity_id
    )
    evolution_scope = EvolutionScope(
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        continuity_id=scope.continuity_id,
    )
    relationship = RelationshipProjection(
        scope=evolution_scope,
        revision=2,
        social=RelationshipSocialStatus.CLOSE_FRIEND,
        romantic=RelationshipRomanticStatus.NONE,
        dynamic=RelationshipDynamic.COMFORTABLE,
        trust=RelationshipTrust.TRUSTING,
        affection=RelationshipAffection.WARM,
    )
    adaptations = PersonaAdaptationProjection(
        scope=evolution_scope,
        revision=1,
        adaptations=(
            PersonaAdaptation(
                facet=AdaptationFacet.COMMUNICATION_STYLE,
                value="Speak with candid warmth.",
            ),
        ),
    )
    messages = tuple(
        Message(
            id=uuid4(),
            scope=scope,
            sequence=i,
            role="user" if role == "user" else "persona",
            content=content,
            created_at=datetime.now(UTC),
        )
        for i, role, content in [(1, "user", "Question"), (2, "persona", "Answer")]
    )
    prompt = assemble_ongoing_prompt(
        persona,
        identity,
        continuity,
        messages,
        "Next",
        relationship=relationship,
        adaptations=adaptations,
    )
    assert prompt[0].content.startswith("Persona core:")
    assert prompt[1].content.startswith("Identity:")
    assert prompt[2].content.startswith("Relationship intent and user boundaries:")
    assert '"intent":"platonic"' in prompt[2].content
    assert prompt[3].content.startswith("Current relationship projection:")
    assert '"social":"close_friend"' in prompt[3].content
    assert '"dynamic":"comfortable"' in prompt[3].content
    assert '"revision"' not in prompt[3].content
    assert prompt[4].content.startswith("Current persona adaptations:")
    assert "Speak with candid warmth." in prompt[4].content
    assert '"revision"' not in prompt[4].content
    assert prompt[5].content.startswith("Response style:")
    assert "Do not invent shared history" in prompt[5].content
    assert [p.role for p in prompt] == ["system"] * 6 + [
        "user",
        "assistant",
        "user",
    ]
    assert [p.content for p in prompt[6:]] == ["Question", "Answer", "Next"]


@pytest.mark.parametrize("extra", [0, 1])
def test_capacity_boundary_includes_fixed_overhead_and_output_reserve(
    characters_session_factory: sessionmaker[Session], extra: int
) -> None:
    """Accept an exact fit and reject one token beyond it.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
        extra:
            Tokens beyond the exact fit.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    original = registry(gateway)
    counter = FixedCounter(8192 - 128 - 64 + extra)
    models = ConfiguredModelRegistry(
        models=original.list_models(),
        responses={"fake": gateway},
        summaries={},
        counters={"fake": counter},
        defaults={"response": ("fake", "first")},
    )
    app = ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        models,
    )
    if extra:
        with pytest.raises(ContextCapacityError):
            app.send(ongoing_target(scope), SubmittedInput(content="Hi"))
        assert app.history(ongoing_target(scope)).attempts == ()
    else:
        assert (
            app.send(ongoing_target(scope), SubmittedInput(content="Hi")).status
            == "pending"
        )
    assert gateway.captured == []


def test_service_reads_current_projections_for_the_next_response(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Use persisted accepted-or-corrected state during response preflight.

    Args:
        characters_session_factory:
            Isolated Characters repositories providing one owned continuity.
    """

    factory = characters_session_factory
    scope = start(factory)
    evolution_scope = EvolutionScope(
        identity_id=scope.identity_id,
        persona_id=scope.persona_id,
        continuity_id=scope.continuity_id,
    )
    repository = Mock(spec=EvolutionRepository)
    repository.get_projections.return_value = EvolutionProjectionState(
        relationship=RelationshipProjection(
            scope=evolution_scope,
            revision=3,
            social=RelationshipSocialStatus.CLOSE_FRIEND,
            romantic=RelationshipRomanticStatus.NONE,
            dynamic=RelationshipDynamic.COMFORTABLE,
            trust=RelationshipTrust.TRUSTING,
            affection=RelationshipAffection.WARM,
        ),
        persona_adaptations=PersonaAdaptationProjection(
            scope=evolution_scope,
            revision=2,
            adaptations=(
                PersonaAdaptation(
                    facet=AdaptationFacet.OPENNESS,
                    value="Share concerns directly instead of deflecting.",
                ),
            ),
        ),
        updated_at=datetime.now(UTC),
    )
    gateway = FakeResponse()
    original = registry(gateway)
    counter = RecordingCounter()
    models = ConfiguredModelRegistry(
        models=original.list_models(),
        responses={"fake": gateway},
        summaries={},
        counters={"fake": counter},
        defaults={"response": ("fake", "first")},
    )
    app = ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        models,
        evolution_projections=repository,
    )

    app.send(ongoing_target(scope), SubmittedInput(content="What do you think?"))

    rendered = "\n".join(message.content for message in counter.prompts[-1])
    assert '"social":"close_friend"' in rendered
    assert "Share concerns directly instead of deflecting." in rendered
    assert '"revision"' not in rendered


def test_context_rejects_same_depth_summary_from_a_sibling_branch(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Match summary coverage by exact checkpoint identity, never path position.

    Args:
        characters_session_factory:
            Isolated Characters repositories providing one owned scope.
    """

    scope = start(characters_session_factory)
    messages = tuple(
        Message(
            id=uuid4(),
            scope=scope,
            sequence=index,
            role="user" if index % 2 else "persona",
            content=f"Message {index}",
            created_at=datetime.now(UTC),
        )
        for index in range(1, 5)
    )
    generation = EffectiveGeneration(
        model=ModelDescriptor(
            provider="fake",
            model="summary",
            context_tokens=512,
            output_tokens=64,
            capabilities=frozenset({"summary"}),
        ),
        configuration=GenerationConfiguration(max_output_tokens=64),
        capability="summary",
        input_tokens=448,
    )
    sibling_summary = SummaryRevision(
        id=uuid4(),
        scope=scope,
        revision=1,
        predecessor_id=None,
        checkpoint_message_id=uuid4(),
        checkpoint_sequence=2,
        content="Summary from an unselected sibling.",
        generation=generation,
        created_at=datetime.now(UTC),
    )
    history = ConversationHistory(
        scope=scope,
        settings=None,
        messages=messages,
        attempts=(),
    )

    with pytest.raises(ValueError, match="selected complete ancestry"):
        OngoingContextEligibility().select(history, sibling_summary, "Next")
