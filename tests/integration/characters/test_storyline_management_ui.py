"""Storyline management UI exercised through real application services."""

from unittest.mock import patch

from sqlalchemy.orm import Session, sessionmaker
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    StorylineService,
)
from chat_buddy.characters.domain import ContinuityLifecycle, PersonaCore
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineRepository,
)
from chat_buddy.characters.ui import new_storyline_page, storylines_page


def _render_new() -> None:
    """Render the New Storyline route with test-supplied services."""

    from chat_buddy.characters.ui import render_new_storyline

    render_new_storyline()


def _render_storylines() -> None:
    """Render the Storylines route with test-supplied services."""

    from chat_buddy.characters.ui import render_storylines_page

    render_storylines_page()


def test_review_start_manage_archive_and_release_pair(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Commit reviewed UI input and manage it through real repositories.

    Args:
        characters_session_factory:
            Isolated PostgreSQL session factory.
    """

    identities = IdentityService(DbIdentityRepository(characters_session_factory))
    personas = PersonaService(DbPersonaRepository(characters_session_factory))
    storylines = StorylineService(
        DbStorylineRepository(characters_session_factory),
        DbSceneRepository(characters_session_factory),
        DbConversationRepository(characters_session_factory),
    )
    persona = personas.create(PersonaCore(name="Guide", definition="Helpful guide"))
    services = (identities, personas, storylines)
    with (
        patch.object(
            new_storyline_page,
            "create_storyline_services",
            return_value=services,
        ),
        patch.object(new_storyline_page, "_navigate_to_storylines"),
        patch.object(
            storylines_page,
            "create_storyline_services",
            return_value=services,
        ),
    ):
        app = AppTest.from_function(_render_new).run()
        app.text_input(key="characters_new_storyline_name").set_value("Long Road")
        app.text_input(key="characters_new_storyline_scene_title").set_value("Arrival")
        app.text_area(key="characters_new_storyline_scene_setup").set_value(
            "A quiet station at dusk."
        )
        app.button(key="characters_new_storyline_preview").click().run()
        request = app.session_state["characters_new_storyline_review"][0]
        assert (
            storylines.list_for_pair(request.identity_id, persona.id).storylines == ()
        )

        app.button(key="characters_new_storyline_confirm").click().run()
        scope = app.session_state["characters_storyline_scope"]
        sequence = storylines.resume(*scope)
        assert sequence.storyline.name == "Long Road"
        assert sequence.scenes[0].details.title == "Arrival"
        assert identities.inspect(request.identity_id).is_frozen
        assert personas.inspect(persona.id).is_frozen

        app = AppTest.from_function(_render_storylines)
        app.session_state["characters_storyline_scope"] = scope
        app.run()
        title = next(item for item in app.text_input if item.label == "Scene title")
        title.set_value("First meeting")
        next(
            button for button in app.button if button.label == "Rename scene"
        ).click().run()
        assert storylines.resume(*scope).scenes[0].details.title == "First meeting"

        setup = next(item for item in app.text_area if item.label == "Scene setup")
        setup.set_value("A rainy station at dusk.")
        next(
            button for button in app.button if button.label == "Save setup"
        ).click().run()
        assert storylines.resume(*scope).scenes[0].details.setup == (
            "A rainy station at dusk."
        )

        app.button(key=f"characters_archive_{scope[2]}").click().run()
        archived = storylines.resume(*scope)
        assert archived.storyline.lifecycle == ContinuityLifecycle.ARCHIVED
        assert storylines.start_availability(scope[0], scope[1]).can_start
        assert any("read-only" in item.value for item in app.info)
        assert not any(button.label == "Next scene" for button in app.button)
