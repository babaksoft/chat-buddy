"""Reviewed UI requests committed through real Characters services and repositories."""

from unittest.mock import patch

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
from chat_buddy.characters.ui import ongoing, page
from tests.characters_support import FakeResponse, service


def _render() -> None:
    """Render Characters with services supplied by the isolated test."""

    from chat_buddy.characters.ui import render

    render()


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
            page,
            "create_profile_services",
            return_value=(identities, personas, continuities),
        ),
        patch.object(
            ongoing,
            "create_conversation_service",
            side_effect=lambda: service(characters_session_factory, gateway),
        ),
    ):
        app = AppTest.from_function(_render).run()
        next(
            button for button in app.button if button.label == "Review start"
        ).click().run()
        request = app.session_state["characters_review"][0]
        assert not continuities.list_grouped()
        assert not identities.inspect(request.identity_id).is_frozen
        assert not personas.inspect(persona.id).is_frozen
        app.button(key="characters_confirm_start").click().run()
        assert not app.exception
        selected = app.session_state["characters_continuity_id"]
        continuity = continuities.resume(request.identity_id, persona.id, selected)
        assert continuities.start(request) == continuity
        assert identities.inspect(request.identity_id).is_frozen
        assert personas.inspect(persona.id).is_frozen
        app.run()
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
        app.button(key=f"characters_select_{selected}").click().run()
        assert not app.exception
        assert any("read-only" in item.value for item in app.info)
        assert not any(button.label == "Archive Ongoing" for button in app.button)
        assert app.chat_input[0].disabled
        assert any(item.value == "Recovered" for item in app.markdown)
        assert len(continuities.list_grouped()[0].continuities) == 1
