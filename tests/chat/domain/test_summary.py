from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.domain import SummaryLifecycle, SummaryProvenance, SummaryRecord
from chat_buddy.chat.utils.fake_data import fake_summary

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_summary_is_immutable_and_active_summary_can_be_superseded() -> None:
    """Summary versions are immutable and permit only active-to-superseded."""

    summary = fake_summary(uuid4())

    assert summary.supersede().lifecycle is SummaryLifecycle.SUPERSEDED
    with pytest.raises(ValueError, match="Only an active"):
        summary.supersede().supersede()
    with pytest.raises(FrozenInstanceError):
        summary.content = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"content": "  "}, "content"),
        ({"created_at": datetime(2026, 1, 1)}, "timezone-aware"),  # noqa: DTZ001
        ({"id": UUID(int=0)}, "nil UUID"),
    ],
)
def test_summary_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    """Summary validation rejects malformed identity, text, and time.

    Args:
        changes:
            Constructor values replacing valid defaults.
        message:
            Expected validation diagnostic.
    """

    conversation_id = uuid4()
    values: dict[str, object] = {
        "id": uuid4(),
        "conversation_id": conversation_id,
        "content": "Summary",
        "created_at": NOW,
        "lifecycle": SummaryLifecycle.ACTIVE,
        "provenance": SummaryProvenance(
            conversation_id=conversation_id,
            checkpoint_message_id=uuid4(),
        ),
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        SummaryRecord(**values)  # type: ignore[arg-type]


def test_summary_provenance_rejects_cross_conversation_ownership() -> None:
    """Summary ownership must agree with its compact checkpoint provenance."""

    conversation_id = uuid4()
    valid_provenance = SummaryProvenance(
        conversation_id=conversation_id,
        checkpoint_message_id=uuid4(),
    )
    with pytest.raises(ValueError, match="another conversation"):
        SummaryRecord(
            id=uuid4(),
            conversation_id=uuid4(),
            content="Summary",
            created_at=NOW,
            lifecycle=SummaryLifecycle.ACTIVE,
            provenance=valid_provenance,
        )


def test_summary_provenance_tracks_checkpoint_progression_without_source_graph() -> (
    None
):
    """Successors carry only predecessor and authoritative assistant checkpoint."""

    predecessor_id = uuid4()
    checkpoint_id = uuid4()
    provenance = SummaryProvenance(
        conversation_id=uuid4(),
        checkpoint_message_id=checkpoint_id,
        predecessor_id=predecessor_id,
    )

    assert provenance.predecessor_id == predecessor_id
    assert provenance.checkpoint_message_id == checkpoint_id
    assert not hasattr(provenance, "newly_covered_sources")
