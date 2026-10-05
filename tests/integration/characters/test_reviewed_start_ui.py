"""Reviewed UI requests committed through real Characters services and repositories."""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import ContinuityLifecycle, PersonaCore
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)
from chat_buddy.characters.ui import new_ongoing_page, ongoing, ongoing_page
from tests.characters_support import FakeResponse, service


def _render() -> None:
    """Render New Ongoing with services supplied by the isolated test."""

    from chat_buddy.characters.ui import render_new_ongoing

    render_new_ongoing()


def _render_ongoing() -> None:
    """Render focused Ongoing navigation with isolated services."""

    from chat_buddy.characters.ui import render_ongoing_page

    render_ongoing_page()


def test_reviewed_start_commits_and_selects_scoped_history(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Review without writes, confirm atomically, then select an archived history.

    Args:
        characters_session_factory:
            Isolated database sessions.
    """

    identities = IdentityService(DbIdentityRepository(characters_session_factory))
    personas = PersonaService(DbPersonaRepository(characters_session_factory))
    continuities = ContinuityService(DbContinuityRepository(characters_session_factory))
    persona = personas.create(PersonaCore(name="Guide", definition="Helpful guide"))
    gateway = FakeResponse()
    with (
        patch.object(
            new_ongoing_page,
            "create_ongoing_services",
            return_value=(identities, personas, continuities),
        ),
        patch.object(new_ongoing_page, "_navigate_to_ongoing"),
        patch.object(
            ongoing_page,
            "create_ongoing_services",
            return_value=(identities, personas, continuities),
        ),
        patch.object(
            ongoing,
            "create_conversation_service",
            side_effect=lambda: service(characters_session_factory, gateway),
        ),
    ):
        app = AppTest.from_function(_render).run()
        app.button(key="characters_new_ongoing_preview").click().run()
        request = app.session_state["characters_new_ongoing_review"][0]
        assert not continuities.list_grouped()
        assert not identities.inspect(request.identity_id).is_frozen
        assert not personas.inspect(persona.id).is_frozen
        app.button(key="characters_new_ongoing_confirm").click().run()
        assert not app.exception
        selected = app.session_state["characters_continuity_id"]
        continuity = continuities.resume(request.identity_id, persona.id, selected)
        assert continuities.start(request) == continuity
        assert identities.inspect(request.identity_id).is_frozen
        assert personas.inspect(persona.id).is_frozen
        scope = app.session_state["characters_continuity_scope"]
        app = AppTest.from_function(_render_ongoing)
        app.session_state["characters_continuity_scope"] = scope
        app.run()
        assert not app.exception
        assert len(continuities.list_grouped()[0].continuities) == 1
        app.chat_input[0].set_value("Hi").run()
        assert not app.exception
        assert any(item.value == "Hello there" for item in app.markdown)
        gateway.chunks, gateway.fail = ("Partial",), True
        app.chat_input[0].set_value("Next").run()
        assert not app.exception
        assert app.error
        app.run()
        assert app.chat_input[0].disabled
        assert any(item.value == "Partial" for item in app.markdown)
        gateway.chunks, gateway.fail = ("Recovered",), False
        next(
            button
            for button in app.button
            if button.label == "Continue incomplete turn"
        ).click().run()
        assert not app.exception
        assert any(item.value == "Recovered" for item in app.markdown)
        assert not any(item.value == "Partial" for item in app.markdown)
        app.button(key="characters_archive").click().run()
        assert not app.exception
        assert (
            continuities.resume(request.identity_id, persona.id, selected).lifecycle
            == ContinuityLifecycle.ARCHIVED
        )
        assert any("read-only" in item.value for item in app.info)
        assert not any(button.label == "Archive Ongoing" for button in app.button)
        assert app.chat_input[0].disabled
        assert any(item.value == "Recovered" for item in app.markdown)
        assert len(continuities.list_grouped()[0].continuities) == 1


def test_concurrent_active_start_disables_real_review_confirmation(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Recheck a reviewed pair after another request starts its active Ongoing.

    Args:
        characters_session_factory:
            Isolated database sessions.
    """

    identities = IdentityService(DbIdentityRepository(characters_session_factory))
    personas = PersonaService(DbPersonaRepository(characters_session_factory))
    continuities = ContinuityService(DbContinuityRepository(characters_session_factory))
    personas.create(PersonaCore(name="Guide", definition="Helpful guide"))
    with (
        patch.object(
            new_ongoing_page,
            "create_ongoing_services",
            return_value=(identities, personas, continuities),
        ),
        patch.object(new_ongoing_page, "_navigate_to_ongoing"),
    ):
        app = AppTest.from_function(_render).run()
        app.button(key="characters_new_ongoing_preview").click().run()
        reviewed = app.session_state["characters_new_ongoing_review"][0]
        concurrent = reviewed.model_copy(update={"request_id": uuid4()})
        created = continuities.start(concurrent)

        app.run()

        assert not app.exception
        assert app.button(key="characters_new_ongoing_confirm").disabled
        assert any("Archive the active Ongoing" in item.value for item in app.warning)
        assert continuities.list_grouped()[0].continuities == (created,)
