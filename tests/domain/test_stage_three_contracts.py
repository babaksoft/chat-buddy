from datetime import UTC, datetime
from uuid import UUID, uuid4

from chat_buddy.chat import domain
from chat_buddy.chat.domain import (
    ConversationRepository,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    ModelId,
    ProviderId,
    SummaryProvenance,
)


class FakeLinearAttemptRepository:
    """Small fake that stores only singular open and retryable selections."""

    def __init__(self) -> None:
        """Initialize empty selections keyed by conversation."""

        self._open: dict[UUID, GenerationAttemptRecord] = {}
        self._retryable: dict[UUID, GenerationAttemptRecord] = {}

    def expose_open(self, attempt: GenerationAttemptRecord | None) -> None:
        """Replace the one open selection for a conversation.

        Args:
            attempt:
                Open attempt to expose, or ``None`` to clear all selections.
        """

        if attempt is None:
            self._open.clear()
            return
        self._open[attempt.conversation_id] = attempt

    def expose_retryable(self, attempt: GenerationAttemptRecord | None) -> None:
        """Replace the one retryable selection for a conversation.

        Args:
            attempt:
                Retryable attempt to expose, or ``None`` to clear selections.
        """

        if attempt is None:
            self._retryable.clear()
            return
        self._retryable[attempt.conversation_id] = attempt

    def get_open_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the singular open selection.

        Args:
            conversation_id:
                Conversation to inspect.

        Returns:
            Open attempt, or ``None``.
        """

        return self._open.get(conversation_id)

    def get_latest_retryable_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the singular retryable selection.

        Args:
            conversation_id:
                Conversation to inspect.

        Returns:
            Latest retryable attempt, or ``None``.
        """

        return self._retryable.get(conversation_id)


def _attempt(
    conversation_id: UUID, status: GenerationAttemptStatus
) -> GenerationAttemptRecord:
    """Create an attempt in an open or retryable state.

    Args:
        conversation_id:
            Owning conversation identifier.
        status:
            Pending, failed, or interrupted status.

    Returns:
        Valid immutable attempt.
    """

    created_at = datetime.now(UTC)
    pending = GenerationAttemptRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        source_user_message_id=uuid4(),
        submitted_user_content="Question",
        provider_id=ProviderId("local"),
        model_id=ModelId("test"),
        effective_configuration=GenerationConfiguration(),
        status=GenerationAttemptStatus.PENDING,
        created_at=created_at,
    )
    if status is GenerationAttemptStatus.PENDING:
        return pending
    streaming = pending.start(at=created_at)
    if status is GenerationAttemptStatus.FAILED:
        return streaming.fail(error_code="provider_error", at=created_at)
    return streaming.interrupt(at=created_at)


def test_repository_contract_has_only_singular_linear_attempt_queries() -> None:
    """Plural unresolved retry-target collections are absent from the contract."""

    assert hasattr(ConversationRepository, "get_open_generation_attempt")
    assert hasattr(ConversationRepository, "get_latest_retryable_generation_attempt")
    assert not hasattr(ConversationRepository, "get_unresolved_generation_attempts")


def test_fake_repository_replaces_open_and_latest_retryable_selections() -> None:
    """A repository consumer can observe at most one selection of each kind."""

    conversation_id = uuid4()
    fake = FakeLinearAttemptRepository()
    first_open = _attempt(conversation_id, GenerationAttemptStatus.PENDING)
    latest_open = _attempt(conversation_id, GenerationAttemptStatus.PENDING)
    first_retryable = _attempt(conversation_id, GenerationAttemptStatus.FAILED)
    latest_retryable = _attempt(conversation_id, GenerationAttemptStatus.INTERRUPTED)

    fake.expose_open(first_open)
    fake.expose_open(latest_open)
    fake.expose_retryable(first_retryable)
    fake.expose_retryable(latest_retryable)

    assert fake.get_open_generation_attempt(conversation_id) == latest_open
    assert (
        fake.get_latest_retryable_generation_attempt(conversation_id)
        == latest_retryable
    )


def test_summary_source_graph_contract_no_longer_exists() -> None:
    """Summary provenance contains no per-attempt source graph."""

    provenance = SummaryProvenance(uuid4(), uuid4())

    assert not hasattr(domain, "SummarySource")
    assert not hasattr(provenance, "newly_covered_sources")
    assert not hasattr(provenance, "newly_covered_attempt_ids")
