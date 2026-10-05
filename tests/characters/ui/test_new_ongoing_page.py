"""Service-double acceptance tests for the dedicated New Ongoing workflow."""

from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import (
    ActiveContinuityError,
    Continuity,
    ContinuityLifecycle,
    ContinuityMode,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    StaleIdentityError,
    StartAvailability,
    StartContinuity,
    StartingOrigins,
    StartingRelationship,
)
from chat_buddy.characters.ui import new_ongoing_page


def _render() -> None:
    """Render only the dedicated New Ongoing page."""

    from chat_buddy.characters.ui import render_new_ongoing

    render_new_ongoing()


@pytest.fixture
def services() -> Generator[tuple[Mock, Mock, Mock, Mock], None, None]:
    """Provide profiles, lifecycle operations, and intercepted navigation.

    Yields:
        Service doubles and the Ongoing navigation double.
    """

    identity = Identity(
        id=uuid4(), details=IdentityDetails(name="You"), is_default=True
    )
    persona = Persona(id=uuid4(), core=PersonaCore(name="Guide", definition="Helpful"))
    identities = Mock(spec=IdentityService)
    personas = Mock(spec=PersonaService)
    continuities = Mock(spec=ContinuityService)
    identities.ensure_default.return_value = identity
    identities.list.return_value = [identity]
    personas.list.return_value = [persona]
    continuities.start_availability.return_value = StartAvailability(can_start=True)

    def start(request: StartContinuity) -> Continuity:
        """Return one continuity for the reviewed request.

        Args:
            request:
                Reviewed start request.

        Returns:
            Matching active Ongoing snapshot.
        """

        continuity = Continuity(
            id=uuid4(),
            identity_id=request.identity_id,
            persona_id=request.persona_id,
            mode=ContinuityMode.ONGOING,
            lifecycle=ContinuityLifecycle.ACTIVE,
            conversation_id=uuid4(),
            relationship=StartingRelationship(
                intent=request.relationship.intent,
                social=request.relationship.social or "stranger",
                romantic=request.relationship.romantic or "none",
                dynamic=request.relationship.dynamic or "neutral",
                trust=request.relationship.trust or "unknown",
                affection=request.relationship.affection or "neutral",
                boundaries=request.relationship.boundaries or (),
                origins=StartingOrigins(
                    social="default",
                    romantic="default",
                    dynamic="default",
                    trust="default",
                    affection="default",
                    boundaries="default",
                ),
            ),
        )
        continuities.created = continuity
        return continuity

    continuities.start.side_effect = start
    with (
        patch.object(
            new_ongoing_page,
            "create_ongoing_services",
            return_value=(identities, personas, continuities),
        ),
        patch.object(new_ongoing_page, "_navigate_to_ongoing") as navigate,
    ):
        yield identities, personas, continuities, navigate


def test_definition_draft_survives_reruns_and_preview_has_no_writes(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Retain draft inputs and create a preview without persistence.

    Args:
        services:
            New Ongoing service and navigation doubles.
    """

    _, _, continuities, _ = services
    app = AppTest.from_function(_render).run()
    assert app.subheader[0].value == "Define Ongoing"
    app.selectbox(key="characters_new_ongoing_intent").set_value(
        RelationshipIntent.OPEN_TO_ROMANCE
    )
    app.selectbox(key="characters_new_ongoing_social").set_value("acquaintance")
    app.run()
    assert (
        app.selectbox(key="characters_new_ongoing_intent").value
        == RelationshipIntent.OPEN_TO_ROMANCE
    )
    assert app.selectbox(key="characters_new_ongoing_social").value == "acquaintance"
    app.button(key="characters_new_ongoing_preview").click().run()

    assert not app.exception
    assert app.subheader[0].value == "Preview Ongoing"
    request = app.session_state["characters_new_ongoing_review"][0]
    assert request.relationship.intent == RelationshipIntent.OPEN_TO_ROMANCE
    assert request.relationship.social == "acquaintance"
    continuities.start.assert_not_called()


@pytest.mark.parametrize("kind", ["identity", "persona"])
def test_profile_revision_change_discards_preview_but_preserves_draft(
    services: tuple[Mock, Mock, Mock, Mock], kind: str
) -> None:
    """Require a new preview after either selected profile changes.

    Args:
        services:
            New Ongoing service and navigation doubles.
        kind:
            Profile whose persisted revision changes.
    """

    profile_service = services[0 if kind == "identity" else 1]
    app = AppTest.from_function(_render).run()
    app.selectbox(key="characters_new_ongoing_social").set_value("close_friend")
    app.button(key="characters_new_ongoing_preview").click().run()
    profile = profile_service.list.return_value[0]
    profile_service.list.return_value = [profile.model_copy(update={"revision": 2})]
    app.run()

    assert not app.exception
    assert "Profiles changed" in app.warning[0].value
    assert app.subheader[0].value == "Define Ongoing"
    assert app.selectbox(key="characters_new_ongoing_social").value == "close_friend"
    assert "characters_new_ongoing_review" not in app.session_state
    services[2].start.assert_not_called()


@pytest.mark.parametrize("preview", [False, True])
def test_cancel_returns_without_writes_or_changing_last_selection(
    services: tuple[Mock, Mock, Mock, Mock], preview: bool
) -> None:
    """Discard either workflow state and preserve the last Ongoing scope.

    Args:
        services:
            New Ongoing service and navigation doubles.
        preview:
            Whether cancellation occurs from preview rather than definition.
    """

    _, _, continuities, navigate = services
    scope = (uuid4(), uuid4(), uuid4())
    app = AppTest.from_function(_render)
    app.session_state["characters_continuity_scope"] = scope
    app.run()
    if preview:
        app.button(key="characters_new_ongoing_preview").click().run()
        key = "characters_new_ongoing_cancel_preview"
    else:
        key = "characters_new_ongoing_cancel_define"
    app.button(key=key).click().run()

    assert not app.exception
    assert app.session_state["characters_continuity_scope"] == scope
    assert "characters_new_ongoing_review" not in app.session_state
    continuities.start.assert_not_called()
    navigate.assert_called_once_with()


def test_confirmation_selects_returned_continuity_and_cannot_replay(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Select the atomic result, clear the request, and navigate to its chat.

    Args:
        services:
            New Ongoing service and navigation doubles.
    """

    _, _, continuities, navigate = services
    app = AppTest.from_function(_render).run()
    app.button(key="characters_new_ongoing_preview").click().run()
    request = app.session_state["characters_new_ongoing_review"][0]
    app.button(key="characters_new_ongoing_confirm").click().run()

    assert not app.exception
    continuities.start.assert_called_once_with(request)
    created = continuities.created
    assert app.session_state["characters_continuity_scope"] == (
        created.identity_id,
        created.persona_id,
        created.id,
    )
    assert "characters_new_ongoing_review" not in app.session_state
    navigate.assert_called_once_with()
    app.run()
    continuities.start.assert_called_once()


def test_availability_is_rechecked_and_concurrent_start_is_visible(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Disable a stale preview and surface a confirmation race safely.

    Args:
        services:
            New Ongoing service and navigation doubles.
    """

    _, _, continuities, navigate = services
    app = AppTest.from_function(_render).run()
    app.button(key="characters_new_ongoing_preview").click().run()
    assert continuities.start_availability.call_count >= 2
    continuities.start.side_effect = ActiveContinuityError(
        "Archive the active Ongoing before starting another"
    )
    app.button(key="characters_new_ongoing_confirm").click().run()
    assert not app.exception
    assert "Archive the active Ongoing" in app.error[0].value
    navigate.assert_not_called()

    continuities.start_availability.return_value = StartAvailability(
        can_start=False,
        reason="Archive the active Ongoing before starting another.",
    )
    app.run()
    assert app.button(key="characters_new_ongoing_confirm").disabled
    assert any("Archive the active Ongoing" in item.value for item in app.warning)


def test_confirmation_revision_race_discards_review_and_retains_draft(
    services: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Recover the definition when confirmation detects a stale profile.

    Args:
        services:
            New Ongoing service and navigation doubles.
    """

    _, _, continuities, navigate = services
    continuities.start.side_effect = StaleIdentityError("Identity changed")
    app = AppTest.from_function(_render).run()
    app.selectbox(key="characters_new_ongoing_social").set_value("close_friend")
    app.button(key="characters_new_ongoing_preview").click().run()
    app.button(key="characters_new_ongoing_confirm").click().run()

    assert not app.exception
    assert "Profiles changed" in app.warning[0].value
    assert "characters_new_ongoing_review" not in app.session_state
    navigate.assert_not_called()
    app.run()
    assert app.subheader[0].value == "Define Ongoing"
    assert app.selectbox(key="characters_new_ongoing_social").value == "close_friend"
