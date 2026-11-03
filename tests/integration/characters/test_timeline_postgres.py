"""PostgreSQL migration and race coverage for Timeline persistence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from chat_buddy.characters.application import (
    TimelineDayService,
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    DayBoundary,
    DayReservationStatus,
    ReserveTimelineDay,
    SubmittedInput,
    TimelineRevisionStatus,
    TimelineStartResult,
    TimelineStartStatus,
)
from chat_buddy.characters.infrastructure.db.models import (
    GenerationAttemptModel,
    MessageModel,
    TimelineDayModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)
from tests.integration.characters.test_continuity_postgres import (
    _chat_snapshot,
    _configuration,
)
from tests.integration.characters.test_timeline_day_service import MutableClock
from tests.integration.characters.test_timeline_repositories import (
    _generation,
    _request,
)

pytestmark = pytest.mark.characters_postgres
PRIOR_HEAD = "7a9c2e4f6b81"


def test_timeline_migration_backfills_style_and_preserves_chat(
    characters_postgres_engine: Engine,
) -> None:
    """Upgrade Stage 7 data, downgrade, and re-upgrade without touching Chat.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine, "chat"), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chat.conversations "
                "(id,title,requested_generation_configuration,created_at,updated_at) "
                "VALUES ('11111111-1111-1111-1111-111111111111',"
                "'Preserve Chat','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    before = _chat_snapshot(engine)
    configuration = _configuration(engine)
    command.upgrade(configuration, PRIOR_HEAD)
    _insert_stage_seven_continuity(engine)

    command.upgrade(configuration, "head")
    command.check(configuration)
    with engine.connect() as connection:
        style = connection.execute(
            text(
                "SELECT scene_description, response_length, narrative_placement, revision "
                "FROM characters.response_style_settings"
            )
        ).one()
        assert style == ("none", "balanced", "interleaved", 1)
    assert _chat_snapshot(engine) == before
    for table in ("timelines", "timeline_days", "response_style_settings"):
        assert all(
            foreign_key["referred_schema"] == "characters"
            for foreign_key in inspect(engine).get_foreign_keys(
                table, schema="characters"
            )
        )

    command.downgrade(configuration, PRIOR_HEAD)
    assert "timelines" not in inspect(engine).get_table_names(schema="characters")
    command.upgrade(configuration, "head")
    command.check(configuration)
    assert _chat_snapshot(engine) == before


def test_concurrent_timeline_starts_have_one_active_slot_winner(
    characters_postgres_engine: Engine,
) -> None:
    """Enforce one active Timeline when two confirmations race.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    request = _request(factory)
    relationship = resolve_starting_relationship(request.relationship)
    other = request.model_copy(update={"request_id": uuid4(), "name": "Other"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda candidate: DbTimelineRepository(factory).start(
                    candidate, relationship
                ),
                (request, other),
            )
        )

    assert all(isinstance(result, TimelineStartResult) for result in results)
    assert sum(result.status == TimelineStartStatus.STARTED for result in results) == 1
    assert (
        sum(
            result.status == TimelineStartStatus.ACTIVE_SLOT_CONFLICT
            for result in results
        )
        == 1
    )


def test_archive_and_first_send_serialize_on_timeline_owner(
    characters_postgres_engine: Engine,
) -> None:
    """Let either archive or first send win without writing after archive.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    request = _request(factory)
    timelines = DbTimelineRepository(factory)
    started = timelines.start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    timeline = started.timeline
    reservation = ReserveTimelineDay(
        timeline_id=timeline.id,
        expected_timeline_revision=timeline.revision,
        expected_selected_leaf_id=None,
        boundary=DayBoundary(
            local_date=date(2026, 11, 3),
            timezone=timeline.calendar_timezone.name,
            opens_at=datetime(2026, 11, 2, 20, 30, tzinfo=UTC),
            closes_at=datetime(2026, 11, 3, 20, 30, tzinfo=UTC),
        ),
        submitted_input=SubmittedInput(content="Hello today"),
        generation=_generation(),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        archive_future = executor.submit(
            timelines.archive,
            timeline.identity_id,
            timeline.persona_id,
            timeline.id,
            timeline.revision,
        )
        send_future = executor.submit(
            DbTimelineDayRepository(factory).reserve_first,
            timeline,
            reservation,
        )
        archived = archive_future.result()
        sent = send_future.result()

    outcomes = (archived.status, sent.status)
    assert outcomes in {
        (TimelineRevisionStatus.UPDATED, DayReservationStatus.ARCHIVED),
        (TimelineRevisionStatus.STALE_REVISION, DayReservationStatus.RESERVED),
    }


def test_two_first_sends_create_one_atomic_day(
    characters_postgres_engine: Engine,
) -> None:
    """Serialize concurrent first sends without duplicate partial records.

    Args:
        characters_postgres_engine:
            Explicit disposable PostgreSQL database.
    """

    engine = characters_postgres_engine
    command.upgrade(_configuration(engine), "head")
    factory = sessionmaker(bind=engine, autoflush=False)
    request = _request(factory)
    started = DbTimelineRepository(factory).start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    timeline = started.timeline
    clock = MutableClock(datetime(2026, 11, 3, 8, tzinfo=UTC))

    def reserve(content: str) -> DayReservationStatus:
        """Reserve one racing first interaction.

        Args:
            content:
                Distinct submitted input.

        Returns:
            Stable reservation outcome.
        """

        service = TimelineDayService(
            DbTimelineRepository(factory),
            DbTimelineDayRepository(factory),
            DbConversationRepository(factory),
            clock,
        )
        return service.reserve(
            timeline.identity_id,
            timeline.persona_id,
            timeline.id,
            SubmittedInput(content=content),
            _generation(),
        ).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            future.result()
            for future in (
                executor.submit(reserve, "First racing send"),
                executor.submit(reserve, "Second racing send"),
            )
        )

    assert outcomes.count(DayReservationStatus.RESERVED) == 1
    assert set(outcomes) <= {
        DayReservationStatus.RESERVED,
        DayReservationStatus.STALE_REVISION,
        DayReservationStatus.DUPLICATE_DATE,
        DayReservationStatus.REUSED_OPEN_DAY,
    }
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(TimelineDayModel)) == 1
        assert session.scalar(select(func.count()).select_from(MessageModel)) == 1
        assert (
            session.scalar(select(func.count()).select_from(GenerationAttemptModel))
            == 1
        )


def _insert_stage_seven_continuity(engine: Engine) -> None:
    """Insert one valid Ongoing owner before the Slice 4 migration.

    Args:
        engine:
            Disposable PostgreSQL engine at the Stage 7 head.
    """

    with engine.begin() as connection:
        connection.execute(text("""
                INSERT INTO characters.identities (id, name, revision, is_frozen)
                VALUES ('22222222-2222-2222-2222-222222222222', 'You', 1, true);
                INSERT INTO characters.personas
                    (id, name, definition, revision, is_frozen)
                VALUES
                    ('33333333-3333-3333-3333-333333333333', 'Guide', 'Helpful', 1, true);
                INSERT INTO characters.continuities
                    (id, identity_id, persona_id, mode, lifecycle, request_id, confirmed_request)
                VALUES (
                    '44444444-4444-4444-4444-444444444444',
                    '22222222-2222-2222-2222-222222222222',
                    '33333333-3333-3333-3333-333333333333',
                    'ongoing', 'active',
                    '55555555-5555-5555-5555-555555555555', '{}'
                )
                """))
