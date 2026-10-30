"""Provider doubles and real repository composition for Characters tests."""

from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ContinuityService, ConversationService
from chat_buddy.characters.domain import (
    BranchModeFactsResolver,
    ContinuityMode,
    ConversationScope,
    ConversationTarget,
    EffectiveGeneration,
    ModelDescriptor,
    PersonaCore,
    PromptMessage,
    ProviderInvocationError,
    RelationshipIntent,
    RelationshipSelection,
    StartContinuity,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import (
    ConfiguredModelRegistry,
    Utf8TokenCounter,
)


class FakeResponse:
    """Capture responses and provide deterministic no-change evolution output."""

    def __init__(self) -> None:
        """Initialize successful output and capture state."""

        self.chunks: tuple[str, ...] = ("Hello", " there")
        self.fail = False
        self.closed = False
        self.captured: list[tuple[PromptMessage, ...]] = []
        self.generations: list[EffectiveGeneration] = []

    def stream(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> Iterator[str]:
        """Yield scripted text and optionally fail after it.

        Args:
            messages:
                Assembled bounded input.
            generation:
                Effective generation provenance.

        Yields:
            Scripted output chunks.

        Raises:
            ProviderInvocationError:
                If scripted failure is enabled.
        """

        self.captured.append(messages)
        self.generations.append(generation)
        try:
            yield from self.chunks
            if self.fail:
                raise ProviderInvocationError("Provider failed")
        finally:
            self.closed = True

    def propose_evolution(
        self,
        messages: tuple[PromptMessage, ...],
        generation: EffectiveGeneration,
        schema: dict[str, object],
    ) -> str:
        """Return a deterministic empty structured evolution proposal.

        Args:
            messages:
                Complete immutable evolution prompt.
            generation:
                Effective evolution model selection.
            schema:
                Structured-output schema.

        Returns:
            Valid no-change provider JSON.
        """

        del messages, generation, schema
        return '{"commands":[]}'


def registry(
    gateway: FakeResponse, context: int = 8192, *, evolution: bool = False
) -> ConfiguredModelRegistry:
    """Build a registry with replaceable response and evolution capabilities.

    Args:
        gateway:
            Capturing fake response capability.
        context:
            Deterministic model context window.
        evolution:
            Whether production-composition tests need the evolution capability.

    Returns:
        Replaceable Characters registry without summary or memory capability.
    """

    return ConfiguredModelRegistry(
        models=tuple(
            ModelDescriptor(
                provider="fake",
                model=name,
                context_tokens=context,
                output_tokens=128,
                capabilities=frozenset(
                    {"response", "evolution"}
                    if evolution and name == "first"
                    else {"response"}
                ),
                parameters=frozenset({"temperature", "seed"}),
            )
            for name in ("first", "second")
        ),
        responses={"fake": gateway},
        summaries={},
        evolutions={"fake": gateway} if evolution else None,
        counters={"fake": Utf8TokenCounter()},
        defaults={
            "response": ("fake", "first"),
            **({"evolution": ("fake", "first")} if evolution else {}),
        },
    )


def service(
    factory: sessionmaker[Session],
    gateway: FakeResponse,
    context: int = 8192,
    branch_mode_facts: BranchModeFactsResolver | None = None,
) -> ConversationService:
    """Compose a fresh service using only real Characters repositories.

    Args:
        factory:
            Isolated database sessions.
        gateway:
            Fake response provider.
        context:
            Model context window.
        branch_mode_facts:
            Optional mode-specific policy facts for branching tests.

    Returns:
        Fresh application service.
    """

    return ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        registry(gateway, context),
        branch_mode_facts,
    )


def start(
    factory: sessionmaker[Session], definition: str = "Helpful guide"
) -> ConversationScope:
    """Create and freeze independent profiles within a new Ongoing.

    Args:
        factory:
            Isolated database sessions.
        definition:
            Distinct authored core for isolation assertions.

    Returns:
        Complete owned conversation scope.
    """

    identity = DbIdentityRepository(factory).ensure_default()
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Guide", definition=definition)
    )
    continuity = ContinuityService(DbContinuityRepository(factory)).start(
        StartContinuity(
            request_id=uuid4(),
            identity_id=identity.id,
            persona_id=persona.id,
            identity_revision=identity.revision,
            persona_revision=persona.revision,
            relationship=RelationshipSelection(intent=RelationshipIntent.PLATONIC),
        )
    )
    return ConversationScope(
        identity_id=identity.id,
        persona_id=persona.id,
        continuity_id=continuity.id,
        conversation_id=continuity.conversation_id,
    )


def ongoing_target(scope: ConversationScope) -> ConversationTarget:
    """Wrap durable ownership in the explicit Ongoing service target.

    Args:
        scope:
            Complete owned conversation scope.

    Returns:
        Mode-owned Ongoing conversation target.
    """

    return ConversationTarget(scope=scope, mode=ContinuityMode.ONGOING)
