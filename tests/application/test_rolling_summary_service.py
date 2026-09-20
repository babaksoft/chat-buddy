"""Tests for conversation-scoped rolling-summary orchestration."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.application.config import RollingSummaryConfig
from chat_buddy.chat.application.service import RollingSummaryService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextInputs,
    GenerationConfiguration,
    GenerationParameter,
    ModelDescriptor,
    ModelId,
    ProviderId,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
)

NOW = datetime(2026, 9, 20, tzinfo=UTC)


class CharacterCounter:
    """Deterministic test counter using formatted content length."""

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Count message-content characters.

        Args:
            messages:
                Messages to measure.

        Returns:
            Combined content length.
        """

        return sum(len(message.content) for message in messages)


class FakeSummaryRepository:
    """In-memory summary persistence with observable replacement calls."""

    def __init__(
        self,
        active: SummaryRecord | None,
        turns: tuple[CompletedTurn, ...],
    ) -> None:
        """Initialize fake state.

        Args:
            active:
                Initially active summary.
            turns:
                Authoritative uncovered turns.
        """

        self.active = active
        self.turns = turns
        self.replacements: list[tuple[SummaryRecord, UUID | None]] = []
        self.fail_replacement = False

    def get_active_summary(self, conversation_id: UUID) -> SummaryRecord | None:
        """Return active state for the selected conversation.

        Args:
            conversation_id:
                Selected conversation identifier.

        Returns:
            Active summary, when present.
        """

        if self.active is None or self.active.conversation_id != conversation_id:
            return None

        return self.active

    def get_summary(self, summary_id: UUID) -> SummaryRecord | None:
        """Return the active record when its identifier matches.

        Args:
            summary_id:
                Requested summary identifier.

        Returns:
            Matching active record, when present.
        """

        if self.active is not None and self.active.id == summary_id:
            return self.active

        return None

    def get_uncovered_completed_turns(
        self, conversation_id: UUID
    ) -> tuple[CompletedTurn, ...]:
        """Return only selected-conversation turns.

        Args:
            conversation_id:
                Selected conversation identifier.

        Returns:
            Configured uncovered turn sequence.
        """

        return self.turns

    def replace_active_summary(
        self,
        summary: SummaryRecord,
        *,
        expected_active_id: UUID | None,
    ) -> SummaryRecord:
        """Record an optimistic summary replacement.

        Args:
            summary:
                New active summary.
            expected_active_id:
                Expected predecessor identifier.

        Returns:
            Supplied summary.
        """

        current_id = self.active.id if self.active is not None else None
        if current_id != expected_active_id:
            raise RuntimeError("stale active summary")

        if self.fail_replacement:
            raise RuntimeError("database unavailable")

        self.replacements.append((summary, expected_active_id))
        self.active = summary
        return summary


class FakeGenerator:
    """Configurable rolling-summary utility fake."""

    def __init__(self, results: list[str | Exception]) -> None:
        """Initialize queued results.

        Args:
            results:
                Values or failures returned in call order.
        """

        self.results = results
        self.calls: list[tuple[str | None, tuple[CompletedTurn, ...]]] = []

    def generate_summary(
        self,
        prior_summary: str | None,
        turns: tuple[CompletedTurn, ...],
    ) -> str:
        """Return or raise the next queued result.

        Args:
            prior_summary:
                Prior durable summary text.
            turns:
                Newly covered turns.

        Returns:
            Queued summary text.

        Raises:
            Exception:
                Queued utility failure.
        """

        self.calls.append((prior_summary, turns))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _model(window: int = 180) -> ModelDescriptor:
    """Create a deterministic model descriptor.

    Args:
        window:
            Context-window size.

    Returns:
        Model descriptor using character counting.
    """

    return ModelDescriptor(
        provider_id=ProviderId("test"),
        id=ModelId("test-model"),
        display_name="Test model",
        context_window_tokens=window,
        supports_streaming=True,
        supported_generation_parameters=frozenset(
            {GenerationParameter.MAX_OUTPUT_TOKENS}
        ),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=CharacterCounter(),
        default_output_token_reserve=20,
    )


def _turn(conversation_id: UUID, offset: int) -> CompletedTurn:
    """Create a completed turn with stable content size.

    Args:
        conversation_id:
            Owning conversation identifier.
        offset:
            Completion-order offset.

    Returns:
        Completed turn.
    """

    return CompletedTurn(
        conversation_id=conversation_id,
        attempt_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        user_content="u" * 20,
        assistant_content="a" * 20,
        completed_at=NOW + timedelta(seconds=offset),
    )


def _summary(conversation_id: UUID, checkpoint: UUID) -> SummaryRecord:
    """Create an active summary.

    Args:
        conversation_id:
            Owning conversation identifier.
        checkpoint:
            Covered assistant message identifier.

    Returns:
        Active summary record.
    """

    return SummaryRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        content="prior summary",
        created_at=NOW,
        lifecycle=SummaryLifecycle.ACTIVE,
        provenance=SummaryProvenance(conversation_id, checkpoint),
    )


def _inputs(conversation_id: UUID) -> ContextInputs:
    """Create one response-boundary input.

    Args:
        conversation_id:
            Selected conversation identifier.

    Returns:
        Context inputs with an unmatched current message.
    """

    return ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "current"),
    )


def _service(
    repository: FakeSummaryRepository,
    generator: FakeGenerator,
) -> RollingSummaryService:
    """Build the service with deterministic policy.

    Args:
        repository:
            Summary persistence fake.
        generator:
            Utility fake.

    Returns:
        Configured rolling-summary service.
    """

    return RollingSummaryService(
        repository=repository,
        generator=generator,
        config=RollingSummaryConfig(
            prompt_overhead_tokens=0,
            summary_trigger_ratio=0.5,
            minimum_recent_turns=2,
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )


def test_first_summary_covers_only_oldest_turn_and_retains_two_recent() -> None:
    """The first version checkpoints the oldest eligible complete-turn prefix."""

    conversation_id = uuid4()
    turns = tuple(_turn(conversation_id, offset) for offset in range(3))
    repository = FakeSummaryRepository(None, turns)
    generator = FakeGenerator([" first durable summary "])

    result = _service(repository, generator).update_summary(
        _inputs(conversation_id),
        _model(),
        GenerationConfiguration(),
    )

    assert result is not None
    assert result.content == "first durable summary"
    assert result.checkpoint_message_id == turns[0].assistant_message_id
    assert result.predecessor_id is None
    assert generator.calls == [(None, turns[:1])]


def test_rolling_replacement_consumes_prior_summary_and_advances_checkpoint() -> None:
    """A replacement uses prior durable text and only newly covered turns."""

    conversation_id = uuid4()
    prior_checkpoint = uuid4()
    active = _summary(conversation_id, prior_checkpoint)
    turns = tuple(_turn(conversation_id, offset) for offset in range(3))
    repository = FakeSummaryRepository(active, turns)
    generator = FakeGenerator(["rolled summary"])

    result = _service(repository, generator).update_summary(
        _inputs(conversation_id),
        _model(),
        GenerationConfiguration(),
    )

    assert result is not None
    assert result.predecessor_id == active.id
    assert result.checkpoint_message_id == turns[0].assistant_message_id
    assert generator.calls == [(active.content, turns[:1])]
    assert repository.replacements[0][1] == active.id


def test_invocation_below_trigger_is_no_op() -> None:
    """An unchanged checkpoint is reused without calling the utility provider."""

    conversation_id = uuid4()
    active = _summary(conversation_id, uuid4())
    repository = FakeSummaryRepository(active, ())
    generator = FakeGenerator([])

    result = _service(repository, generator).update_summary(
        _inputs(conversation_id),
        _model(window=1_000),
        GenerationConfiguration(),
    )

    assert result == active
    assert generator.calls == []
    assert repository.replacements == []


def test_repeated_active_checkpoint_in_uncovered_turns_is_rejected() -> None:
    """Unsafe non-advancing repository coverage cannot generate a replacement."""

    conversation_id = uuid4()
    turn = _turn(conversation_id, 0)
    active = _summary(conversation_id, turn.assistant_message_id)
    repository = FakeSummaryRepository(active, (turn,))
    generator = FakeGenerator([])

    with pytest.raises(ValueError, match="repeat the active checkpoint"):
        _service(repository, generator).update_summary(
            _inputs(conversation_id),
            _model(),
            GenerationConfiguration(),
        )

    assert generator.calls == []


def test_utility_failure_preserves_prior_summary_and_later_call_retries() -> None:
    """Best-effort failure retains durable state and does not suppress retry."""

    conversation_id = uuid4()
    active = _summary(conversation_id, uuid4())
    turns = tuple(_turn(conversation_id, offset) for offset in range(3))
    repository = FakeSummaryRepository(active, turns)
    generator = FakeGenerator([RuntimeError("offline"), "recovered summary"])
    service = _service(repository, generator)

    first = service.update_summary(
        _inputs(conversation_id),
        _model(),
        GenerationConfiguration(),
    )
    second = service.update_summary(
        _inputs(conversation_id),
        _model(),
        GenerationConfiguration(),
    )

    assert first == active
    assert second is not None
    assert second.content == "recovered summary"
    assert len(generator.calls) == 2
    assert len(repository.replacements) == 1


def test_persistence_failure_preserves_prior_summary_and_later_call_retries() -> None:
    """A failed atomic replacement leaves the prior version retryable."""

    conversation_id = uuid4()
    active = _summary(conversation_id, uuid4())
    turns = tuple(_turn(conversation_id, offset) for offset in range(3))
    repository = FakeSummaryRepository(active, turns)
    repository.fail_replacement = True
    generator = FakeGenerator(["first result", "second result"])
    service = _service(repository, generator)

    first = service.update_summary(
        _inputs(conversation_id),
        _model(),
        GenerationConfiguration(),
    )
    repository.fail_replacement = False
    second = service.update_summary(
        _inputs(conversation_id),
        _model(),
        GenerationConfiguration(),
    )

    assert first == active
    assert second is not None
    assert second.content == "second result"
    assert repository.replacements == [(second, active.id)]
