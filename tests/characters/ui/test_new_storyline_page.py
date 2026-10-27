"""Acceptance tests for the dedicated New Storyline workflow."""

from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ActiveStorylineError,
    ContinuityLifecycle,
    ConversationScope,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    Scene,
    StartAvailability,
    StartingOrigins,
    StartingRelationship,
    StartStoryline,
    Storyline,
)
from chat_buddy.characters.ui import new_storyline_page


def _render() -> None:
    """Render only the dedicated New Storyline page."""

    from chat_buddy.characters.ui import render_new_storyline

    render_new_storyline()


@pytest.fixture
def services() -> Generator[tuple[Mock, Mock, Mock, Mock], None, None]:
    """Provide profile, lifecycle, and navigation doubles.

    Yields:
        Service doubles and intercepted Storyline navigation.
    """

    identity = Identity(
        id=uuid4(), details=IdentityDetails(name="You"), is_default=True
    )
    persona = Persona(id=uuid4(), core=PersonaCore(name="Guide", definition="Helpful"))
    identities = Mock(spec=IdentityService)
    personas = Mock(spec=PersonaService)
    storylines = Mock(spec=StorylineService)
    identities.ensure_default.return_value = identity
    identities.list.return_value = [identity]
    personas.list.return_value = [persona]
    storylines.start_availability.return_value = StartAvailability(can_start=True)

    def start(request: StartStoryline) -> tuple[Storyline, Scene]:
        """Build a matching start result.

        Args:
            request:
                Reviewed Storyline request.

        Returns:
            Matching Storyline and initial scene.
        """

        storyline = Storyline(
            id=uuid4(),
            identity_id=request.identity_id,
            persona_id=request.persona_id,
            name=request.name,
            lifecycle=ContinuityLifecycle.ACTIVE,
            relationship=_relationship(),
            revision=1,
        )
        scene = Scene(
            id=uuid4(),
            scope=ConversationScope(
                identity_id=storyline.identity_id,
                persona_id=storyline.persona_id,
                continuity_id=storyline.id,
                conversation_id=uuid4(),
            ),
            position=1,
            details=request.initial_scene,
            setup_locked=False,
        )
        storylines.created = (storyline, scene)
        return storyline, scene

    storylines.start.side_effect = start
    with (
        patch.object(
            new_storyline_page,
            "create_storyline_services",
            return_value=(identities, personas, storylines),
        ),
        patch.object(new_storyline_page, "_navigate_to_storylines") as navigate,
    ):
        yield identities, personas, storylines, navigate


def test_review_has_no_writes_and_preserves_complete_definition(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Create a complete immutable preview without persistence.

    Args:
        services:
            Storyline service and navigation doubles.
    """

    storylines = services[2]
    app = AppTest.from_function(_render).run()
    app.text_input(key="characters_new_storyline_name").set_value("Long Road")
    app.text_input(key="characters_new_storyline_scene_title").set_value("Arrival")
    app.text_area(key="characters_new_storyline_scene_setup").set_value(
        "A quiet station at dusk."
    )
    app.selectbox(key="characters_new_storyline_intent").set_value(
        RelationshipIntent.OPEN_TO_ROMANCE
    )
    app.button(key="characters_new_storyline_preview").click().run()

    assert not app.exception
    request = app.session_state["characters_new_storyline_review"][0]
    assert request.name == "Long Road"
    assert request.initial_scene.title == "Arrival"
    assert request.initial_scene.response_style.name == "storyline.default"
    assert request.relationship.intent == RelationshipIntent.OPEN_TO_ROMANCE
    storylines.start.assert_not_called()


def test_changed_profile_invalidates_review_and_restores_draft(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Require review again after a selected profile revision changes.

    Args:
        services:
            Storyline service and navigation doubles.
    """

    identities = services[0]
    app = _defined_app()
    app.button(key="characters_new_storyline_preview").click().run()
    identity = identities.list.return_value[0]
    identities.list.return_value = [identity.model_copy(update={"revision": 2})]
    app.run()

    assert "Profiles changed" in app.warning[0].value
    assert app.subheader[0].value == "Define Storyline"
    assert app.text_input(key="characters_new_storyline_name").value == "Long Road"
    assert "characters_new_storyline_review" not in app.session_state


def test_confirm_selects_initial_scene_and_cannot_replay(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Select the committed result and clear the replayable review.

    Args:
        services:
            Storyline service and navigation doubles.
    """

    storylines, navigate = services[2], services[3]
    app = _defined_app()
    app.button(key="characters_new_storyline_preview").click().run()
    request = app.session_state["characters_new_storyline_review"][0]
    app.button(key="characters_new_storyline_confirm").click().run()

    storylines.start.assert_called_once_with(request)
    storyline, scene = storylines.created
    assert app.session_state["characters_storyline_scope"] == (
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
    )
    assert app.session_state["characters_scene_id"] == scene.id
    assert "characters_new_storyline_review" not in app.session_state
    navigate.assert_called_once_with()
    app.run()
    storylines.start.assert_called_once()


def test_active_pair_conflict_remains_in_review(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Surface a concurrent active-pair conflict without losing review.

    Args:
        services:
            Storyline service and navigation doubles.
    """

    storylines, navigate = services[2], services[3]
    app = _defined_app()
    app.button(key="characters_new_storyline_preview").click().run()
    storylines.start.side_effect = ActiveStorylineError("Archive the active Storyline")
    app.button(key="characters_new_storyline_confirm").click().run()

    assert "Archive the active Storyline" in app.error[0].value
    assert "characters_new_storyline_review" in app.session_state
    navigate.assert_not_called()


def _defined_app() -> AppTest:
    """Populate the required Storyline definition fields.

    Returns:
        Executed app with a valid draft.
    """

    app = AppTest.from_function(_render).run()
    app.text_input(key="characters_new_storyline_name").set_value("Long Road")
    app.text_input(key="characters_new_storyline_scene_title").set_value("Arrival")
    app.text_area(key="characters_new_storyline_scene_setup").set_value(
        "A quiet station at dusk."
    )
    return app


def _relationship() -> StartingRelationship:
    """Create the resolved default starting relationship.

    Returns:
        Valid immutable relationship snapshot.
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
