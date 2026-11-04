"""Executable shared Continuity Entry domain and repository contracts."""

import inspect
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    ContinuityEntry,
    ContinuityEntryRepository,
    ContinuityMode,
    EntryPosition,
)


def _entry(mode: ContinuityMode = ContinuityMode.STORYLINE) -> ContinuityEntry:
    """Create one valid immutable Entry.

    Args:
        mode:
            Narrative mode represented by the Entry.

    Returns:
        Valid shared Entry snapshot.
    """

    return ContinuityEntry(
        id=uuid4(),
        continuity_id=uuid4(),
        identity_id=uuid4(),
        persona_id=uuid4(),
        conversation_id=uuid4(),
        mode=mode,
        position=1,
    )


def test_entry_exposes_exact_scope_and_position_without_duplicate_fields() -> None:
    """Derive shared views from the Entry's single ownership source."""

    entry = _entry()

    assert entry.scope.identity_id == entry.identity_id
    assert entry.scope.persona_id == entry.persona_id
    assert entry.scope.continuity_id == entry.continuity_id
    assert entry.scope.conversation_id == entry.conversation_id
    assert entry.entry_position == EntryPosition(
        entry_id=entry.id,
        continuity_id=entry.continuity_id,
        mode=entry.mode,
        position=entry.position,
    )
    assert set(entry.model_dump()) == {
        "id",
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
        "mode",
        "position",
    }


def test_entry_values_are_frozen_and_reject_ongoing_or_invalid_positions() -> None:
    """Allow only immutable positive Storyline and Timeline Entries."""

    entry = _entry(ContinuityMode.TIMELINE)
    with pytest.raises(ValidationError):
        entry.position = 2
    with pytest.raises(ValidationError, match="do not have Entries"):
        _entry(ContinuityMode.ONGOING)
    with pytest.raises(ValidationError):
        ContinuityEntry.model_validate({**entry.model_dump(), "position": 0})


def test_entry_positions_order_only_inside_one_continuity_and_mode() -> None:
    """Reject comparisons whose numeric positions have unrelated meaning."""

    continuity_id = uuid4()
    first = EntryPosition(
        entry_id=uuid4(),
        continuity_id=continuity_id,
        mode=ContinuityMode.STORYLINE,
        position=1,
    )
    second = first.model_copy(update={"entry_id": uuid4(), "position": 2})

    assert first < second
    with pytest.raises(ValueError, match="one continuity and mode"):
        assert first < second.model_copy(update={"continuity_id": uuid4()})
    with pytest.raises(ValueError, match="one continuity and mode"):
        assert first < second.model_copy(update={"mode": ContinuityMode.TIMELINE})
    with pytest.raises(TypeError):
        assert first < 2
    with pytest.raises(ValidationError, match="do not have Entry positions"):
        EntryPosition(
            entry_id=uuid4(),
            continuity_id=continuity_id,
            mode=ContinuityMode.ONGOING,
            position=1,
        )


def test_entry_repository_is_read_only_and_ownership_scoped() -> None:
    """Expose only exact lookup and ordered continuity listing operations."""

    assert ContinuityEntryRepository._is_protocol  # type: ignore[attr-defined]
    public_methods = {
        name
        for name, value in inspect.getmembers(
            ContinuityEntryRepository, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }

    assert public_methods == {"get", "list"}
