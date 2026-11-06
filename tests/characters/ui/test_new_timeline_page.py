"""Acceptance tests for the dedicated New Timeline workflow."""

from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    TimelineService,
    default_response_style,
)
from chat_buddy.characters.domain import (
    ApplicationLocalTimezone,
    ContinuityLifecycle,
    ContinuityMode,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    StartingOrigins,
    StartingRelationship,
    Timeline,
    TimelineStartResult,
    TimelineStartReview,
    TimelineStartStatus,
    VersionedResponseStyleSettings,
)
from chat_buddy.characters.ui import new_timeline_page


def _render() -> None:
    """Render only the focused New Timeline page."""

    from chat_buddy.characters.ui import render_new_timeline

    render_new_timeline()


@pytest.fixture
def services() -> Generator[tuple[Mock, Mock, Mock, Mock], None, None]:
    """Provide profile, Timeline, and navigation doubles.

    Yields:
        Service doubles and intercepted Timeline navigation.
    """

    identity = Identity(
        id=uuid4(), details=IdentityDetails(name="You"), is_default=True
    )
    persona = Persona(id=uuid4(), core=PersonaCore(name="Guide", definition="Helpful"))
    identities = Mock(spec=IdentityService)
    personas = Mock(spec=PersonaService)
    timelines = Mock(spec=TimelineService)
    identities.ensure_default.return_value = identity
    identities.list.return_value = [identity]
    personas.list.return_value = [persona]
    timelines.start_availability.return_value.can_start = True
    timelines.start_availability.return_value.reason = None

    def start(request: TimelineStartReview) -> TimelineStartResult:
        """Return a successful start matching the reviewed owners.

        Args:
            request:
                Reviewed Timeline request.

        Returns:
            Successful start result without any represented day.
        """

        timeline = Timeline(
            id=uuid4(),
            identity_id=request.identity_id,
            persona_id=request.persona_id,
            name=request.name,
            lifecycle=ContinuityLifecycle.ACTIVE,
            relationship=_relationship(),
            calendar_timezone=ApplicationLocalTimezone(name="Asia/Tehran"),
            revision=1,
        )
        timelines.created = timeline
        return TimelineStartResult(
            status=TimelineStartStatus.STARTED,
            timeline=timeline,
            style=VersionedResponseStyleSettings(
                settings=default_response_style(ContinuityMode.TIMELINE), revision=1
            ),
        )

    timelines.start.side_effect = start
    with (
        patch.object(
            new_timeline_page,
            "create_timeline_services",
            return_value=(identities, personas, timelines),
        ),
        patch.object(new_timeline_page, "_navigate_to_timelines") as navigate,
    ):
        yield identities, personas, timelines, navigate


def test_preview_reviews_profiles_and_relationship_without_timezone_or_day_write(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Prepare the complete review without timezone input or persistence.

    Args:
        services:
            Timeline workflow doubles.
    """

    timelines = services[2]
    app = AppTest.from_function(_render).run()
    assert not any("timezone" in item.label.lower() for item in app.text_input)
    app.text_input(key="characters_new_timeline_name").set_value("Ordinary Days")
    app.selectbox(key="characters_new_timeline_intent").set_value(
        RelationshipIntent.OPEN_TO_ROMANCE
    )
    app.button(key="characters_new_timeline_preview").click().run()

    request = app.session_state["characters_new_timeline_review"][0]
    assert request.name == "Ordinary Days"
    assert request.relationship.intent == RelationshipIntent.OPEN_TO_ROMANCE
    assert request.response_style == default_response_style(ContinuityMode.TIMELINE)
    assert "calendar_timezone" not in type(request).model_fields
    timelines.start.assert_not_called()
    timelines.resume.assert_not_called()


def test_invalid_relationship_stays_in_definition_with_guidance(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Surface domain validation without creating a review or Timeline.

    Args:
        services:
            Timeline workflow doubles.
    """

    app = AppTest.from_function(_render).run()
    app.text_input(key="characters_new_timeline_name").set_value("Ordinary Days")
    app.selectbox(key="characters_new_timeline_romantic").set_value("dating")
    app.button(key="characters_new_timeline_preview").click().run()

    assert app.error
    assert "Platonic intent" in app.error[0].value
    assert "characters_new_timeline_review" not in app.session_state
    services[2].start.assert_not_called()


def test_confirm_is_idempotent_in_ui_state_and_creates_no_day(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Confirm once, store complete scope, and remove replayable review state.

    Args:
        services:
            Timeline workflow doubles.
    """

    timelines, navigate = services[2], services[3]
    app = AppTest.from_function(_render).run()
    app.text_input(key="characters_new_timeline_name").set_value("Ordinary Days")
    app.button(key="characters_new_timeline_preview").click().run()
    request = app.session_state["characters_new_timeline_review"][0]
    app.button(key="characters_new_timeline_confirm").click().run()

    timelines.start.assert_called_once_with(request)
    created = timelines.created
    assert app.session_state["characters_timeline_scope"] == (
        created.identity_id,
        created.persona_id,
        created.id,
    )
    assert "characters_new_timeline_review" not in app.session_state
    timelines.resume.assert_not_called()
    navigate.assert_called_once_with()
    app.run()
    timelines.start.assert_called_once()


def _relationship() -> StartingRelationship:
    """Create a resolved default starting relationship.

    Returns:
        Immutable relationship snapshot.
    """

    return StartingRelationship(
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
    )
