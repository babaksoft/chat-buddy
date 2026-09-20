from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.application.schemas import MemoryManagementOutcome
from chat_buddy.chat.application.service import MemoryManagementService
from chat_buddy.chat.domain import (
    ChatRole,
    ConversationRecord,
    MemoryDeletionResult,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
    MessageRecord,
)

NOW = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)


def _memory(*, lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE) -> MemoryRecord:
    """Create one extracted memory for service tests.

    Args:
        lifecycle:
            Current lifecycle for the memory.

    Returns:
        Valid extracted memory record.
    """

    return MemoryRecord(
        id=uuid4(),
        revision_id=uuid4(),
        subject="location",
        content="The user lives in Tehran.",
        lifecycle=lifecycle,
        origin=MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            conversation_id=uuid4(),
            user_message_id=uuid4(),
            assistant_message_id=uuid4(),
            generation_attempt_id=uuid4(),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _service(
    memory: MemoryRecord | None,
) -> tuple[MemoryManagementService, Mock, Mock]:
    """Build a service with repository mocks and resolved source records.

    Args:
        memory:
            Current memory returned by the repository.

    Returns:
        Service, memory repository mock, and conversation repository mock.
    """

    memories = Mock()
    memories.get_memory.return_value = memory
    memories.list_memories.return_value = () if memory is None else (memory,)
    conversations = Mock()
    if (
        memory is not None
        and memory.origin.kind is MemoryOriginKind.EXTRACTED
        and memory.origin.source_available
    ):
        origin = memory.origin
        assert origin.conversation_id is not None
        assert origin.user_message_id is not None
        assert origin.assistant_message_id is not None
        conversations.get_conversation.return_value = ConversationRecord(
            id=origin.conversation_id,
            title="Travel",
        )
        messages = {
            origin.user_message_id: MessageRecord(
                id=origin.user_message_id,
                conversation_id=origin.conversation_id,
                role=ChatRole.USER,
                content="I live in Tehran.",
            ),
            origin.assistant_message_id: MessageRecord(
                id=origin.assistant_message_id,
                conversation_id=origin.conversation_id,
                role=ChatRole.ASSISTANT,
                content="Thanks for telling me.",
            ),
        }
        conversations.get_message.side_effect = messages.get
    service = MemoryManagementService(
        memories,
        conversations,
        clock=lambda: NOW + timedelta(seconds=1),
        revision_id_factory=lambda: UUID("00000000-0000-0000-0000-000000000123"),
    )
    return service, memories, conversations


def test_lists_by_state_and_resolves_source_information() -> None:
    """Verify listing delegates state filtering and resolves the source turn."""

    memory = _memory()
    service, memories, _ = _service(memory)

    result = service.list_memories(frozenset({MemoryLifecycle.ACTIVE}))

    memories.list_memories.assert_called_once_with(frozenset({MemoryLifecycle.ACTIVE}))
    assert len(result) == 1
    assert result[0].id == memory.id
    assert result[0].provenance.source is not None
    assert result[0].provenance.source.conversation_title == "Travel"
    assert result[0].provenance.source.user_message_content == "I live in Tehran."
    assert (
        result[0].provenance.source.assistant_message_content
        == "Thanks for telling me."
    )


def test_inspection_reports_unavailable_source_without_repository_lookups() -> None:
    """Verify unavailable provenance remains inspectable without source records."""

    original = _memory()
    memory = MemoryRecord(
        id=original.id,
        revision_id=original.revision_id,
        subject=original.subject,
        content=original.content,
        lifecycle=original.lifecycle,
        origin=MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            source_available=False,
        ),
        created_at=original.created_at,
        updated_at=original.updated_at,
    )
    service, _, conversations = _service(memory)

    result = service.inspect_memory(memory.id)

    assert result is not None
    assert result.provenance.source_available is False
    assert result.provenance.source is None
    conversations.get_conversation.assert_not_called()
    conversations.get_message.assert_not_called()


def test_correction_normalizes_content_and_records_user_provenance() -> None:
    """Verify correction constructs and returns an active replacement revision."""

    memory = _memory()
    service, memories, _ = _service(memory)
    memories.replace_memory.side_effect = lambda replacement, **_: replacement

    result = service.correct_memory(
        memory.id,
        expected_revision_id=memory.revision_id,
        subject="  Home   Location ",
        content=" The user   lives in Shiraz. ",
    )

    replacement = memories.replace_memory.call_args.args[0]
    assert result.outcome is MemoryManagementOutcome.UPDATED
    assert result.memory is not None
    assert replacement.subject == "home location"
    assert replacement.content == "The user lives in Shiraz."
    assert replacement.origin.kind is MemoryOriginKind.USER_CORRECTION
    assert replacement.origin.superseded_revision_id == memory.revision_id
    assert result.memory.provenance.source is None


def test_correction_rejects_excluded_memory() -> None:
    """Verify correction cannot silently undo a user's exclusion."""

    memory = _memory(lifecycle=MemoryLifecycle.EXCLUDED)
    service, memories, _ = _service(memory)

    with pytest.raises(ValueError, match="reactivated"):
        service.correct_memory(
            memory.id,
            expected_revision_id=memory.revision_id,
            subject=memory.subject,
            content="Changed.",
        )

    memories.replace_memory.assert_not_called()


def test_exclusion_and_reactivation_are_stable_when_repeated() -> None:
    """Verify lifecycle actions update once and then report unchanged."""

    active = _memory()
    service, memories, _ = _service(active)
    excluded = active.transition(
        MemoryLifecycle.EXCLUDED,
        at=NOW + timedelta(seconds=1),
    )
    memories.transition_memory.return_value = excluded

    first = service.exclude_memory(
        active.id,
        expected_revision_id=active.revision_id,
    )
    memories.get_memory.return_value = excluded
    repeated = service.exclude_memory(
        active.id,
        expected_revision_id=active.revision_id,
    )
    memories.transition_memory.return_value = active
    reactivated = service.reactivate_memory(
        active.id,
        expected_revision_id=active.revision_id,
    )

    assert first.outcome is MemoryManagementOutcome.UPDATED
    assert repeated.outcome is MemoryManagementOutcome.UNCHANGED
    assert reactivated.outcome is MemoryManagementOutcome.UPDATED
    assert memories.transition_memory.call_count == 2


def test_missing_and_stale_targets_do_not_mutate() -> None:
    """Verify preflight checks report missing and stale targets without writes."""

    service, memories, _ = _service(None)
    missing = service.exclude_memory(uuid4(), expected_revision_id=uuid4())
    memories.get_memory.return_value = _memory()
    stale = service.reactivate_memory(uuid4(), expected_revision_id=uuid4())

    assert missing.outcome is MemoryManagementOutcome.NOT_FOUND
    assert stale.outcome is MemoryManagementOutcome.STALE
    memories.transition_memory.assert_not_called()


def test_concurrent_correction_and_transition_are_reported_as_stale() -> None:
    """Verify repository race detection becomes a stable application outcome."""

    memory = _memory()
    service, memories, _ = _service(memory)
    memories.replace_memory.side_effect = RuntimeError("changed")
    correction = service.correct_memory(
        memory.id,
        expected_revision_id=memory.revision_id,
        subject=memory.subject,
        content="The user lives in Shiraz.",
    )
    memories.transition_memory.side_effect = RuntimeError("changed")
    transition = service.exclude_memory(
        memory.id,
        expected_revision_id=memory.revision_id,
    )

    assert correction.outcome is MemoryManagementOutcome.STALE
    assert transition.outcome is MemoryManagementOutcome.STALE


@pytest.mark.parametrize(
    ("repository_result", "expected_outcome"),
    [
        (MemoryDeletionResult.DELETED, MemoryManagementOutcome.UPDATED),
        (MemoryDeletionResult.NOT_FOUND, MemoryManagementOutcome.NOT_FOUND),
        (MemoryDeletionResult.STALE, MemoryManagementOutcome.STALE),
    ],
)
def test_hard_delete_reports_terminal_repository_outcome(
    repository_result: MemoryDeletionResult,
    expected_outcome: MemoryManagementOutcome,
) -> None:
    """Verify hard deletion exposes deleted, repeated, and stale outcomes.

    Args:
        repository_result:
            Terminal result supplied by persistence.
        expected_outcome:
            Expected application-facing outcome.
    """

    memory = _memory()
    service, memories, _ = _service(memory)
    memories.hard_delete.return_value = repository_result

    result = service.delete_memory(
        memory.id,
        expected_revision_id=memory.revision_id,
    )

    assert result.outcome is expected_outcome
    assert result.memory is None
    memories.hard_delete.assert_called_once_with(
        memory.id,
        expected_revision_id=memory.revision_id,
    )
