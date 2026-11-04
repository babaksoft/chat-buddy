"""Persistence coverage for normalized Continuity Entry ownership."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import ContinuityNotFoundError
from chat_buddy.characters.infrastructure.db.models import SceneModel, TimelineDayModel
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityEntryRepository,
)
from tests.characters_support import FakeResponse
from tests.integration.characters.test_storyline_repositories import (
    _relationship,
    _repositories_and_request,
)
from tests.integration.characters.test_timeline_conversations import (
    FakeSummary,
    MutableClock,
    _start_day,
)


def test_entry_repository_reads_both_subtypes_from_one_owned_shape(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Read Storyline and Timeline Entries without subtype-owned shared columns.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, _, request = _repositories_and_request(factory)
    storyline, scene = storylines.start(request, _relationship())
    _, target = _start_day(
        factory,
        MutableClock(datetime(2026, 11, 4, 8, tzinfo=UTC)),
        FakeResponse(),
        FakeSummary(),
        "Start the represented day.",
    )
    assert target.entry_id is not None

    entries = DbContinuityEntryRepository(factory)
    assert entries.get(scene.scope, scene.id) == scene.entry
    assert entries.list(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        "storyline",
    ) == (scene.entry,)
    assert entries.get(target.scope, target.entry_id).mode == "timeline"

    with pytest.raises(ContinuityNotFoundError):
        entries.get(scene.scope.model_copy(update={"identity_id": uuid4()}), scene.id)

    columns = inspect(factory.kw["bind"]).get_columns("scenes")
    shared = {
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
        "mode",
        "position",
    }
    assert shared.isdisjoint(column["name"] for column in columns)


def test_subtype_discriminators_reject_cross_mode_entries(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject attaching either detail subtype to the other Entry mode.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, _, request = _repositories_and_request(factory)
    _, scene = storylines.start(request, _relationship())
    _, target = _start_day(
        factory,
        MutableClock(datetime(2026, 11, 4, 8, tzinfo=UTC)),
        FakeResponse(),
        FakeSummary(),
        "Start the represented day.",
    )
    assert target.entry_id is not None

    with pytest.raises(IntegrityError), factory() as session, session.begin():
        session.execute(
            update(SceneModel)
            .where(SceneModel.id == scene.id)
            .values(entry_mode="timeline")
        )
    with pytest.raises(IntegrityError), factory() as session, session.begin():
        session.execute(
            update(TimelineDayModel)
            .where(TimelineDayModel.id == target.entry_id)
            .values(entry_mode="storyline")
        )
