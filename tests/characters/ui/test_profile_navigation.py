"""Service-double acceptance tests for deliberate Characters setup and navigation."""

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
    ContinuityGroup,
    ContinuityLifecycle,
    ContinuityMode,
    FrozenIdentityError,
    FrozenPersonaError,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    StaleIdentityError,
    StalePersonaError,
    StartContinuity,
    StartingOrigins,
    StartingRelationship,
)
from chat_buddy.characters.ui import page


def _render() -> None:
    """Render only Characters for isolated Streamlit acceptance."""

    from chat_buddy.characters.ui import render

    render()


@pytest.fixture
def services() -> Generator[tuple[Mock, Mock, Mock], None, None]:
    """Provide application doubles with editable snapshots and a start result.

    Yields:
        Identity, persona, and continuity service doubles.
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
    continuities.list_grouped.return_value = ()

    def start(request: StartContinuity) -> Continuity:
        """Commit a simulated reviewed request and expose it in navigation.

        Args:
            request:
                Reviewed immutable request.

        Returns:
            A matching active continuity.
        """

        relationship = StartingRelationship(
            intent=request.relationship.intent,
            social=request.relationship.social or "stranger",
            romantic=request.relationship.romantic or "none",
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
        row = Continuity(
            id=uuid4(),
            identity_id=request.identity_id,
            persona_id=request.persona_id,
            mode=ContinuityMode.ONGOING,
            lifecycle=ContinuityLifecycle.ACTIVE,
            conversation_id=uuid4(),
            relationship=relationship,
        )
        continuities.list_grouped.return_value = (
            ContinuityGroup(
                identity_id=row.identity_id,
                persona_id=row.persona_id,
                continuities=(row,),
            ),
        )
        continuities.resume.return_value = row
        return row

    continuities.start.side_effect = start
    with (
        patch.object(
            page,
            "create_profile_services",
            return_value=(identities, personas, continuities),
        ),
    ):
        yield identities, personas, continuities


def test_empty_setup_creates_default_and_inline_persona(
    services: tuple[Mock, Mock, Mock],
) -> None:
    """Offer You and allow the first persona without creating a continuity.

    Args:
        services:
            Application doubles.
    """

    identities, personas, continuities = services
    persona = personas.list.return_value[0]
    personas.list.return_value = []
    personas.create.return_value = persona
    app = AppTest.from_function(_render).run()
    assert not app.exception
    assert "Identity: You" in app.caption[0].value
    next(
        widget for widget in app.text_input if widget.label == "Persona name"
    ).set_value("Guide")
    app.text_area[0].set_value("Helpful")
    next(
        button for button in app.button if button.label == "Create persona"
    ).click().run()
    assert not app.exception
    personas.create.assert_called_once_with(
        PersonaCore(name="Guide", definition="Helpful")
    )
    identities.ensure_default.assert_called()
    continuities.start.assert_not_called()


@pytest.mark.parametrize("intent", list(RelationshipIntent))
def test_review_cancel_confirm_and_reruns(
    services: tuple[Mock, Mock, Mock], intent: RelationshipIntent
) -> None:
    """Only confirmation starts, retaining reviewed ownership across reruns.

    Args:
        services:
            Application doubles.
        intent:
            Relationship direction to exercise.
    """

    identities, personas, continuities = services
    app = AppTest.from_function(_render).run()
    app.selectbox(key="characters_intent").set_value(intent)
    if intent == RelationshipIntent.ESTABLISHED:
        app.selectbox(key="characters_social").set_value("close_friend")
        app.selectbox(key="characters_romantic").set_value("partner")
    next(
        button for button in app.button if button.label == "Review start"
    ).click().run()
    request = app.session_state["characters_review"][0]
    app.run()
    assert app.session_state["characters_review"][0] == request
    continuities.start.assert_not_called()
    app.button(key="characters_cancel_start").click().run()
    continuities.start.assert_not_called()
    identities.edit.assert_not_called()
    personas.edit.assert_not_called()
    next(
        button for button in app.button if button.label == "Review start"
    ).click().run()
    request = app.session_state["characters_review"][0]
    app.button(key="characters_confirm_start").click().run()
    assert not app.exception
    continuities.start.assert_called_once_with(request)
    assert request.identity_id == identities.list.return_value[0].id
    assert request.persona_id == personas.list.return_value[0].id
    assert request.relationship.intent == intent
    app.run()
    continuities.start.assert_called_once()
    created = continuities.list_grouped.return_value[0].continuities[0]
    assert app.session_state["characters_continuity_scope"] == (
        created.identity_id,
        created.persona_id,
        created.id,
    )
    continuities.start.assert_called_once()


@pytest.mark.parametrize("kind", ["identity", "persona"])
def test_changed_profiles_require_fresh_review(
    services: tuple[Mock, Mock, Mock], kind: str
) -> None:
    """Discard stale revisions and require deliberate renewed review.

    Args:
        services:
            Application doubles.
        kind:
            Profile being edited externally.
    """

    service = services[0 if kind == "identity" else 1]
    app = AppTest.from_function(_render).run()
    next(
        button for button in app.button if button.label == "Review start"
    ).click().run()
    profile = service.list.return_value[0]
    service.list.return_value = [profile.model_copy(update={"revision": 2})]
    app.run()
    assert not app.exception
    assert "Profiles changed" in app.warning[0].value
    assert not any(button.label == "Confirm start" for button in app.button)
    services[2].start.assert_not_called()


@pytest.mark.parametrize(
    "error", [ActiveContinuityError, StaleIdentityError, StalePersonaError]
)
def test_confirmation_errors_are_visible(
    services: tuple[Mock, Mock, Mock], error: type[ValueError]
) -> None:
    """Surface start conflicts without retrying or silently replacing a continuity.

    Args:
        services:
            Application doubles.
        error:
            Concurrent submission failure.
    """

    services[2].start.side_effect = error("Archive the active Ongoing first")
    app = AppTest.from_function(_render).run()
    next(
        button for button in app.button if button.label == "Review start"
    ).click().run()
    app.button(key="characters_confirm_start").click().run()
    assert not app.exception
    assert app.error or app.warning
    services[2].start.assert_called_once()
    services[2].archive.assert_not_called()


@pytest.mark.parametrize("kind", ["identity", "persona"])
def test_inline_edits_creation_and_frozen_duplication(
    services: tuple[Mock, Mock, Mock], kind: str
) -> None:
    """Route editable saves and creation, then allow frozen profile duplication.

    Args:
        services:
            Application doubles.
        kind:
            Profile type to manage.
    """

    service = services[0 if kind == "identity" else 1]
    profile = service.list.return_value[0]
    service.edit.return_value = profile
    service.create.return_value = profile
    service.duplicate.return_value = profile.model_copy(
        update={"id": uuid4(), "is_frozen": False}
    )
    app = AppTest.from_function(_render).run()
    next(
        button for button in app.button if button.label == f"Save {kind}"
    ).click().run()
    assert not app.exception
    service.edit.assert_called_once_with(
        profile.id,
        profile.details if kind == "identity" else profile.core,
        profile.revision,
    )
    new_name = "New profile"
    next(
        widget for widget in app.text_input if widget.label == f"{kind.title()} name"
    ).set_value(new_name)
    if kind == "persona":
        app.text_area[0].set_value("New definition")
    next(
        button for button in app.button if button.label == f"Create {kind}"
    ).click().run()
    assert not app.exception
    assert service.create.call_args.args[0].name == new_name
    service.list.return_value = [profile.model_copy(update={"is_frozen": True})]
    app.run()
    assert next(
        button for button in app.button if button.label == f"Save {kind}"
    ).disabled
    app.button(key=f"characters_duplicate_{kind}_{profile.id}").click().run()
    assert not app.exception
    service.duplicate.assert_called_once_with(profile.id)


@pytest.mark.parametrize(
    "kind,error", [("identity", FrozenIdentityError), ("persona", FrozenPersonaError)]
)
def test_concurrent_freeze_is_visible(
    services: tuple[Mock, Mock, Mock], kind: str, error: type[ValueError]
) -> None:
    """Expose a first-use freeze racing with an editable form submission.

    Args:
        services:
            Application doubles.
        kind:
            Profile type to edit.
        error:
            Concurrent freeze failure.
    """

    service = services[0 if kind == "identity" else 1]
    service.edit.side_effect = error("Duplicate this frozen profile to edit it")
    app = AppTest.from_function(_render).run()
    next(
        button for button in app.button if button.label == f"Save {kind}"
    ).click().run()
    assert not app.exception
    assert "Duplicate" in app.error[0].value


def test_invalid_established_start_does_not_create_review(
    services: tuple[Mock, Mock, Mock],
) -> None:
    """Reject missing established inputs before a start can be confirmed.

    Args:
        services:
            Application doubles.
    """

    app = AppTest.from_function(_render).run()
    app.selectbox(key="characters_intent").set_value(RelationshipIntent.ESTABLISHED)
    next(
        button for button in app.button if button.label == "Review start"
    ).click().run()
    assert not app.exception
    assert "Established starts require" in app.error[0].value
    services[2].start.assert_not_called()


def test_combined_page_no_longer_renders_ongoing_history(
    services: tuple[Mock, Mock, Mock],
) -> None:
    """Keep history and conversation rendering on the focused Ongoing page.

    Args:
        services:
            Application doubles.
    """

    _, _, continuities = services
    app = AppTest.from_function(_render).run()

    assert not app.exception
    continuities.list_grouped.assert_not_called()
    continuities.resume.assert_not_called()
    continuities.archive.assert_not_called()
    assert not any(
        button.key and button.key.startswith("characters_select_")
        for button in app.button
    )
