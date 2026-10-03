"""Bounded durable Ongoing rolling-summary context behavior."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ContextCapacityError,
    ConversationNotFoundError,
    EffectiveGeneration,
    ModelDescriptor,
    PromptMessage,
    ProviderInvocationError,
    SubmittedInput,
    SummaryConflictError,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import ConfiguredModelRegistry
from tests.characters_support import FakeResponse, start


class MessageCountCounter:
    """Assign ten tokens to every rendered provider message."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Return a deterministic framing-sensitive count.

        Args:
            messages:
                Complete provider input.

        Returns:
            Ten tokens per message.
        """

        return len(messages) * 10


class FakeSummary:
    """Capture summary prompts and return short numbered revisions."""

    def __init__(self, fail: bool = False) -> None:
        """Initialize capture and optional provider failure.

        Args:
            fail:
                Whether every generation should fail.
        """

        self.fail = fail
        self.captured: list[tuple[PromptMessage, ...]] = []

    def summarize(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> str:
        """Capture exact inputs and return deterministic content.

        Args:
            messages:
                Bounded prior summary and new complete turns.
            generation:
                Effective summary provenance.

        Returns:
            Short numbered summary.

        Raises:
            ProviderInvocationError:
                If failure was requested.
        """

        self.captured.append(messages)
        if self.fail:
            raise ProviderInvocationError("Summary failed")
        return f"Durable summary {len(self.captured)}"


def test_long_context_advances_revisions_and_resumes_from_durable_checkpoint(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Compress oldest prefixes, preserve order, and resume in a fresh service.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    responses = FakeResponse()
    summaries = FakeSummary()
    app = _service(factory, responses, summaries)
    for text in ("First", "Second", "Third"):
        attempt = app.send(scope, SubmittedInput(content=text))
        list(app.stream(scope, attempt.id))

    fourth = app.send(scope, SubmittedInput(content="Fourth"))
    active = DbSummaryRepository(factory).get_active(scope)
    assert active is not None
    assert active.revision == 2
    assert active.checkpoint_sequence == 4
    assert len(summaries.captured) == 2
    assert "Prior summary:" not in "".join(
        message.content for message in summaries.captured[0]
    )
    assert "Prior summary:\nDurable summary 1" in "".join(
        message.content for message in summaries.captured[1]
    )
    list(app.stream(scope, fourth.id))
    prompt = responses.captured[-1]
    assert prompt[4].content == "Conversation summary:\nDurable summary 2"
    assert [message.content for message in prompt[-3:]] == [
        "Third",
        "Hello there",
        "Fourth",
    ]
    assert all("First" not in message.content for message in prompt)

    restarted = _service(factory, responses, summaries)
    fifth = restarted.send(scope, SubmittedInput(content="Fifth"))
    resumed = DbSummaryRepository(factory).get_active(scope)
    assert resumed is not None
    assert resumed.revision == 3
    assert resumed.checkpoint_sequence == 6
    list(restarted.stream(scope, fifth.id))
    assert restarted.history(scope).messages[-1].content == "Hello there"

    previous = restarted.history(scope)
    responses.chunks, responses.fail = ("Partial",), True
    failed = restarted.send(scope, SubmittedInput(content="Sixth"))
    with pytest.raises(ProviderInvocationError):
        list(restarted.stream(scope, failed.id))
    responses.chunks, responses.fail = ("Recovered",), False
    recovered = _service(factory, responses, summaries)
    restored = recovered.resume(scope)
    assert restored.settings == previous.settings
    assert restored.attempts[-1].incomplete_output == "Partial"
    assert restored.messages[:-1] == previous.messages
    continued = recovered.continue_incomplete_turn(scope)
    assert continued.user_message_id == failed.user_message_id
    assert list(recovered.stream(scope, continued.id)) == ["Recovered"]
    assert recovered.history(scope).messages[-1].content == "Recovered"
    assert all(message.content != "Partial" for message in responses.captured[-1])


def test_required_summary_failure_preserves_history_and_active_revision(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Expose a recoverable capacity failure without reserving a response attempt.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    responses = FakeResponse()
    working = _service(factory, responses, FakeSummary())
    for text in ("First", "Second", "Third"):
        attempt = working.send(scope, SubmittedInput(content=text))
        list(working.stream(scope, attempt.id))
    before = working.history(scope)
    failing_summary = FakeSummary(fail=True)
    failing = _service(factory, responses, failing_summary)
    with pytest.raises(ContextCapacityError, match="compression failed"):
        failing.send(scope, SubmittedInput(content="Fourth"))
    assert failing.history(scope) == before
    assert DbSummaryRepository(factory).get_active(scope) is None
    assert len(failing_summary.captured) == 1


def test_summary_repository_requires_ownership_and_rejects_stale_replacement(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Fence foreign reads and allow only one successor for an observed lineage.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    foreign = start(factory, "Foreign persona")
    responses = FakeResponse()
    summaries = FakeSummary()
    app = _service(factory, responses, summaries)
    for text in ("First", "Second", "Third"):
        attempt = app.send(scope, SubmittedInput(content=text))
        list(app.stream(scope, attempt.id))
    fourth = app.send(scope, SubmittedInput(content="Fourth"))
    repository = DbSummaryRepository(factory)
    active = repository.get_active(scope)
    assert active is not None
    checkpoint = app.history(scope).messages[5]
    successor = active.model_copy(
        update={
            "id": uuid4(),
            "revision": active.revision + 1,
            "predecessor_id": active.id,
            "checkpoint_message_id": checkpoint.id,
            "checkpoint_sequence": checkpoint.sequence,
            "content": "Manual valid successor",
        }
    )
    saved = repository.replace(successor, active.revision, active.checkpoint_message_id)
    assert saved.revision == active.revision + 1
    stale = successor.model_copy(
        update={
            "id": uuid4(),
            "content": "Losing stale successor",
        }
    )
    with pytest.raises(SummaryConflictError):
        repository.replace(stale, active.revision, active.checkpoint_message_id)
    for field in ("continuity_id", "conversation_id"):
        bad_scope = scope.model_copy(update={field: getattr(foreign, field)})
        with pytest.raises(ConversationNotFoundError):
            repository.get_active(bad_scope)
    list(app.stream(scope, fourth.id))


def _service(
    factory: sessionmaker[Session],
    responses: FakeResponse,
    summaries: FakeSummary,
) -> ConversationService:
    """Compose real repositories with deterministic bounded fake capabilities.

    Args:
        factory:
            Isolated Characters sessions.
        responses:
            Capturing streaming provider.
        summaries:
            Capturing summary provider.

    Returns:
        Fresh durable Ongoing service.
    """

    models = (
        ModelDescriptor(
            provider="fake",
            model="response",
            context_tokens=170,
            output_tokens=10,
            capabilities=frozenset({"response"}),
        ),
        ModelDescriptor(
            provider="fake",
            model="summary",
            context_tokens=170,
            output_tokens=10,
            capabilities=frozenset({"summary"}),
        ),
    )
    registry = ConfiguredModelRegistry(
        models=models,
        responses={"fake": responses},
        summaries={"fake": summaries},
        counters={"fake": MessageCountCounter()},
        defaults={
            "response": ("fake", "response"),
            "summary": ("fake", "summary"),
        },
    )
    return ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        registry,
    )
