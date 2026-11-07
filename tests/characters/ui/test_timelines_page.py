"""Acceptance tests for Timeline and represented-day navigation."""

from collections.abc import Generator
from datetime import UTC, date, datetime
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    TimelineService,
)
from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    ContinuityEntry,
    ContinuityLifecycle,
    ContinuityMode,
    DayBoundary,
    DayReservationResult,
    DayReservationStatus,
    GenerationAttempt,
    Identity,
    IdentityDetails,
    Message,
    Persona,
    PersonaCore,
    RelationshipIntent,
    StartAvailability,
    StartingOrigins,
    StartingRelationship,
    Timeline,
    TimelineDay,
    TimelineGroup,
    TimelineNavigation,
    TimelineRevisionResult,
    TimelineRevisionStatus,
)
from chat_buddy.characters.ui import timelines_page


def _render() -> None:
    """Render only the focused Timelines page."""

    from chat_buddy.characters.ui import render_timelines_page

    render_timelines_page()


@pytest.fixture
def services() -> Generator[tuple[Mock, Mock, Mock, TimelineNavigation], None, None]:
    """Provide profile and Timeline navigation doubles.

    Yields:
        Services and an active navigation with a local-date gap.
    """

    identity = Identity(
        id=uuid4(), details=IdentityDetails(name="You"), is_default=True
    )
    persona = Persona(id=uuid4(), core=PersonaCore(name="Guide", definition="Helpful"))
    active = _timeline(identity.id, persona.id, ContinuityLifecycle.ACTIVE)
    archived = _timeline(identity.id, persona.id, ContinuityLifecycle.ARCHIVED)
    navigation = TimelineNavigation(
        timeline=active,
        days=(
            _day(active, 1, date(2026, 10, 31), closed=True),
            _day(active, 2, date(2026, 11, 2), closed=False),
        ),
    )
    identities = Mock(spec=IdentityService)
    personas = Mock(spec=PersonaService)
    timelines = Mock(spec=TimelineService)
    identities.ensure_default.return_value = identity
    identities.list.return_value = [identity]
    personas.list.return_value = [persona]
    timelines.list_grouped.return_value = (
        TimelineGroup(
            identity_id=identity.id,
            persona_id=persona.id,
            timelines=(active, archived),
        ),
    )
    timelines.start_availability.return_value = StartAvailability(
        can_start=False, reason="Archive the active Timeline before starting another."
    )
    timelines.resume.return_value = navigation
    timelines.archive.return_value = TimelineRevisionResult(
        status=TimelineRevisionStatus.UPDATED,
        timeline=active.model_copy(
            update={"lifecycle": ContinuityLifecycle.ARCHIVED, "revision": 2}
        ),
    )
    with (
        patch.object(
            timelines_page,
            "create_timeline_services",
            return_value=(identities, personas, timelines),
        ),
        patch.object(timelines_page, "_prepare_start") as navigate,
        patch.object(timelines_page, "render_response_style") as style,
        patch.object(timelines_page, "render_conversation") as conversation,
        patch.object(timelines_page, "render_storyline_memory") as memory,
        patch.object(timelines_page, "render_evolution_inspection"),
        patch.object(timelines_page, "create_continuity_memory_service"),
        patch.object(timelines_page, "create_evolution_inspection_service"),
        patch.object(timelines_page, "create_conversation_service"),
        patch.object(
            timelines_page, "create_timeline_interaction_services"
        ) as interactions,
        patch.object(timelines_page, "stream_attempt") as stream,
    ):
        interactions.return_value = (Mock(), Mock(), Mock())
        timelines.navigate = navigate
        timelines.style = style
        timelines.conversation = conversation
        timelines.memory = memory
        timelines.interactions = interactions
        timelines.stream = stream
        yield identities, personas, timelines, navigation


def test_navigation_separates_lifecycle_and_preserves_missing_calendar_days(
    services: tuple[Mock, Mock, Mock, TimelineNavigation],
) -> None:
    """Show stored dates only and resume by complete ownership.

    Args:
        services:
            Timeline services and active navigation.
    """

    timelines, navigation = services[2], services[3]
    app = AppTest.from_function(_render).run()
    assert any(item.value == "Active" for item in app.sidebar.caption)
    assert any(item.value == "Archived" for item in app.sidebar.caption)
    app.button(key=f"characters_select_timeline_{navigation.timeline.id}").click().run()

    scope = (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    timelines.resume.assert_called_with(*scope)
    labels = [button.label for button in app.button]
    assert any("2026-10-31 · closed" == label for label in labels)
    assert any("2026-11-02 · current · open" == label for label in labels)
    assert not any("2026-11-01" in label for label in labels)
    assert not any("clock" in item.value.lower() for item in app.caption)


def test_resume_renders_application_observed_offline_closure(
    services: tuple[Mock, Mock, Mock, TimelineNavigation],
) -> None:
    """Render closure returned by the service without consulting a UI clock.

    Args:
        services:
            Timeline services and active navigation.
    """

    timelines, navigation = services[2], services[3]
    latest = navigation.days[-1]
    closed = latest.model_copy(
        update={
            "closed_at": latest.boundary.closes_at,
            "settled_selected_leaf_id": uuid4(),
        }
    )
    timelines.resume.return_value = navigation.model_copy(
        update={"days": (navigation.days[0], closed)}
    )
    app = AppTest.from_function(_render)
    app.session_state["characters_timeline_scope"] = (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    app.run()

    assert any("2026-11-02 · closed" == button.label for button in app.button)
    assert any("closed and permanently read-only" in item.value for item in app.info)


def test_empty_timeline_is_valid_and_navigation_creates_no_day(
    services: tuple[Mock, Mock, Mock, TimelineNavigation],
) -> None:
    """Explain an empty Timeline without invoking any day reservation.

    Args:
        services:
            Timeline services and active navigation.
    """

    timelines, navigation = services[2], services[3]
    timelines.resume.return_value = navigation.model_copy(update={"days": ()})
    app = AppTest.from_function(_render)
    app.session_state["characters_timeline_scope"] = (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    app.run()

    assert any("No days have been represented yet" in item.value for item in app.info)
    assert not hasattr(timelines, "reserve")


def test_archive_requires_confirmation_and_preserves_selection(
    services: tuple[Mock, Mock, Mock, TimelineNavigation],
) -> None:
    """Archive under the observed revision only after explicit confirmation.

    Args:
        services:
            Timeline services and active navigation.
    """

    timelines, navigation = services[2], services[3]
    app = AppTest.from_function(_render)
    scope = (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    app.session_state["characters_timeline_scope"] = scope
    app.run()
    archive = app.button(key=f"characters_archive_timeline_{navigation.timeline.id}")
    assert archive.disabled
    app.checkbox(
        key=f"characters_archive_timeline_confirm_{navigation.timeline.id}"
    ).check().run()
    app.button(
        key=f"characters_archive_timeline_{navigation.timeline.id}"
    ).click().run()

    timelines.archive.assert_called_once_with(*scope, navigation.timeline.revision)
    assert app.session_state["characters_timeline_scope"] == scope


def test_closed_day_explains_absent_graph_actions_and_reuses_derived_panels(
    services: tuple[Mock, Mock, Mock, TimelineNavigation],
) -> None:
    """Render closed history with early guidance plus Timeline-scoped tools.

    Args:
        services:
            Timeline services and active navigation.
    """

    timelines, navigation = services[2], services[3]
    closed = navigation.days[0]
    app = AppTest.from_function(_render)
    app.session_state["characters_timeline_scope"] = (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    app.session_state["characters_timeline_day_id"] = closed.id
    app.run()

    assert not app.exception
    call = timelines.conversation.call_args
    assert call.kwargs["read_only"] is True
    assert "Retry, alternative selection" in call.kwargs["read_only_reason"]
    timelines.memory.assert_called_once()
    assert timelines.memory.call_args.kwargs["mode_label"] == "Timeline"


def test_first_send_reserves_day_atomically_then_streams_owned_attempt(
    services: tuple[Mock, Mock, Mock, TimelineNavigation],
) -> None:
    """Create no day until input, then stream the exact atomic reservation.

    Args:
        services:
            Timeline services and active navigation.
    """

    timelines, navigation = services[2], services[3]
    timelines.resume.return_value = navigation.model_copy(update={"days": ()})
    days, _, generation = timelines.interactions.return_value
    reserved_day = navigation.days[-1]
    attempt = GenerationAttempt.model_construct(id=uuid4())
    days.reserve.return_value = DayReservationResult(
        status=DayReservationStatus.RESERVED,
        day=reserved_day,
        user_message=Message.model_construct(),
        attempt=attempt,
    )
    app = AppTest.from_function(_render)
    app.session_state["characters_timeline_scope"] = (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    app.run()
    days.reserve.assert_not_called()

    app.chat_input[0].set_value("Hello today").run()

    days.reserve.assert_called_once()
    assert days.reserve.call_args.args[:3] == (
        navigation.timeline.identity_id,
        navigation.timeline.persona_id,
        navigation.timeline.id,
    )
    assert days.reserve.call_args.args[3].content == "Hello today"
    assert days.reserve.call_args.args[4] is generation
    timelines.stream.assert_called_once()
    target = timelines.stream.call_args.args[1]
    assert target.scope == reserved_day.scope
    assert target.entry_id == reserved_day.id
    assert timelines.stream.call_args.args[2] is attempt


def _timeline(
    identity_id: UUID, persona_id: UUID, lifecycle: ContinuityLifecycle
) -> Timeline:
    """Build one Timeline snapshot.

    Args:
        identity_id:
            Owning identity.
        persona_id:
            Owning persona.
        lifecycle:
            Active or archived state.

    Returns:
        Immutable Timeline snapshot.
    """

    return Timeline(
        id=uuid4(),
        identity_id=identity_id,
        persona_id=persona_id,
        name=f"{lifecycle.value.title()} Days",
        lifecycle=lifecycle,
        relationship=StartingRelationship(
            intent=RelationshipIntent.PLATONIC,
            social="stranger",
            romantic="none",
            dynamic="neutral",
            trust="unknown",
            affection="neutral",
            boundaries=(),
            origins=StartingOrigins(
                social="default",
                romantic="default",
                dynamic="default",
                trust="default",
                affection="default",
                boundaries="default",
            ),
        ),
        calendar_timezone=ApplicationLocalTimezone(name="America/New_York"),
        revision=1,
    )


def _day(
    timeline: Timeline, position: int, local_date: date, *, closed: bool
) -> TimelineDay:
    """Build one represented day around the fall DST transition.

    Args:
        timeline:
            Owning Timeline.
        position:
            Immutable Entry position.
        local_date:
            Stored local date.
        closed:
            Whether closure has been observed.

    Returns:
        Represented day snapshot.
    """

    opens = {
        date(2026, 10, 31): datetime(2026, 10, 31, 4, tzinfo=UTC),
        date(2026, 11, 2): datetime(2026, 11, 2, 5, tzinfo=UTC),
    }
    closes = {
        date(2026, 10, 31): datetime(2026, 11, 1, 4, tzinfo=UTC),
        date(2026, 11, 2): datetime(2026, 11, 3, 5, tzinfo=UTC),
    }
    leaf_id = uuid4() if closed else None
    return TimelineDay(
        entry=ContinuityEntry(
            id=uuid4(),
            identity_id=timeline.identity_id,
            persona_id=timeline.persona_id,
            continuity_id=timeline.id,
            conversation_id=uuid4(),
            mode=ContinuityMode.TIMELINE,
            position=position,
        ),
        boundary=DayBoundary(
            local_date=local_date,
            timezone=timeline.calendar_timezone.name,
            opens_at=opens[local_date],
            closes_at=closes[local_date],
        ),
        closed_at=closes[local_date] if closed else None,
        settled_selected_leaf_id=leaf_id,
    )
