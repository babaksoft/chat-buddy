"""Characters mandatory block ordering and deterministic capacity boundaries."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ContextCapacityError,
    Message,
    PromptMessage,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)
from chat_buddy.characters.infrastructure.llm import ConfiguredModelRegistry
from chat_buddy.characters.prompts import assemble_ongoing_prompt
from tests.characters_support import FakeResponse, registry, start


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
    prompt = assemble_ongoing_prompt(persona, identity, continuity, messages, "Next")
    assert prompt[0].content.startswith("Persona core:")
    assert prompt[1].content.startswith("Identity:")
    assert prompt[2].content.startswith("Relationship intent and starting state:")
    assert '"intent":"platonic"' in prompt[2].content
    assert '"social":"stranger"' in prompt[2].content
    assert '"romantic":"none"' in prompt[2].content
    assert "Do not invent shared history" in prompt[2].content
    assert prompt[3].content.startswith("Respond as the persona")
    assert [p.role for p in prompt] == ["system"] * 4 + ["user", "assistant", "user"]
    assert [p.content for p in prompt[4:]] == ["Question", "Answer", "Next"]


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
        models,
    )
    if extra:
        with pytest.raises(ContextCapacityError):
            app.send(scope, SubmittedInput(content="Hi"))
        assert app.history(scope).attempts == ()
    else:
        assert app.send(scope, SubmittedInput(content="Hi")).status == "pending"
    assert gateway.captured == []
