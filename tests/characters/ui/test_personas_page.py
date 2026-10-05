"""Service-double acceptance tests for focused persona management."""

from collections.abc import Generator
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import PersonaService
from chat_buddy.characters.domain import (
    FrozenPersonaError,
    Persona,
    PersonaCore,
    StalePersonaError,
)
from chat_buddy.characters.ui import personas_page


def _render() -> None:
    """Render only the focused Personas page."""

    from chat_buddy.characters.ui import render_personas

    render_personas()


@pytest.fixture
def persona_service() -> Generator[Mock, None, None]:
    """Provide persona application operations and persisted snapshots.

    Yields:
        Configured persona service double.
    """

    first = Persona(
        id=uuid4(),
        core=PersonaCore(
            name="Guide",
            definition="A patient librarian who helps with difficult research.",
            traits="Curious",
        ),
    )
    second = Persona(
        id=uuid4(),
        core=PersonaCore(name="Traveler", definition="Always looking ahead."),
    )
    service = Mock(spec=PersonaService)
    service.list.return_value = [first, second]
    with patch.object(personas_page, "create_persona_service", return_value=service):
        yield service


def test_lists_names_definition_excerpts_and_edit_state(
    persona_service: Mock,
) -> None:
    """Show authored definition excerpts and edit state in the master list.

    Args:
        persona_service:
            Persona service double.
    """

    long_definition = "word " * 30
    first = cast(Persona, persona_service.list.return_value[0])
    persona_service.list.return_value[0] = first.model_copy(
        update={"core": first.core.model_copy(update={"definition": long_definition})}
    )
    app = AppTest.from_function(_render).run()

    assert not app.exception
    assert app.title[0].value == "🎭 Personas"
    assert any("..." in item.value and "Editable" in item.value for item in app.caption)
    assert app.button(key=f"characters_persona_manage_{first.id}")
    assert (
        next(field for field in app.text_input if field.label == "Persona name").value
        == "Guide"
    )
    assert [button.label for button in app.button].count("Save changes") == 1


def test_selects_only_one_persona_editor(persona_service: Mock) -> None:
    """Replace the visible editor when another persona is selected.

    Args:
        persona_service:
            Persona service double.
    """

    selected = cast(Persona, persona_service.list.return_value[1])
    app = AppTest.from_function(_render).run()
    app.button(key=f"characters_persona_manage_{selected.id}").click().run()

    assert not app.exception
    assert app.session_state["characters_persona_id"] == selected.id
    assert (
        next(field for field in app.text_input if field.label == "Persona name").value
        == "Traveler"
    )
    assert len([area for area in app.text_area if area.label == "Definition"]) == 1


def test_empty_setup_creates_and_immediately_selects_persona(
    persona_service: Mock,
) -> None:
    """Create the first persona and select its persisted snapshot.

    Args:
        persona_service:
            Persona service double.
    """

    persona_service.list.return_value = []
    created = Persona(
        id=uuid4(), core=PersonaCore(name="New persona", definition="A new friend")
    )

    def create(core: PersonaCore) -> Persona:
        """Expose the simulated persisted result to the following rerun.

        Args:
            core:
                Submitted authored persona core.

        Returns:
            Newly persisted persona snapshot.
        """

        saved = created.model_copy(update={"core": core})
        persona_service.list.return_value.append(saved)
        return saved

    persona_service.create.side_effect = create
    app = AppTest.from_function(_render).run()
    next(field for field in app.text_input if field.label == "Persona name").set_value(
        "New persona"
    )
    next(area for area in app.text_area if area.label == "Definition").set_value(
        "A new friend"
    )
    next(
        button for button in app.button if button.label == "Create persona"
    ).click().run()

    assert not app.exception
    persona_service.create.assert_called_once_with(
        PersonaCore(name="New persona", definition="A new friend")
    )
    assert app.session_state["characters_persona_id"] == created.id
    assert app.button(key=f"characters_persona_manage_{created.id}")
    assert (
        next(field for field in app.text_input if field.label == "Persona name").value
        == "New persona"
    )


def test_saves_editable_persona_with_expected_revision(
    persona_service: Mock,
) -> None:
    """Replace an unused persona and retain its stable selection.

    Args:
        persona_service:
            Persona service double.
    """

    original = cast(Persona, persona_service.list.return_value[0])

    def edit(persona_id: object, core: PersonaCore, expected_revision: int) -> Persona:
        """Replace the service double's current snapshot.

        Args:
            persona_id:
                Stable persona identifier.
            core:
                Submitted replacement core.
            expected_revision:
                Revision displayed in the form.

        Returns:
            Revised persisted persona snapshot.
        """

        revised = original.model_copy(
            update={"core": core, "revision": expected_revision + 1}
        )
        persona_service.list.return_value[0] = revised
        return revised

    persona_service.edit.side_effect = edit
    app = AppTest.from_function(_render).run()
    next(area for area in app.text_area if area.label == "Definition").set_value(
        "A revised guide"
    )
    next(
        button for button in app.button if button.label == "Save changes"
    ).click().run()

    assert not app.exception
    replacement = persona_service.edit.call_args.args[1]
    assert replacement.definition == "A revised guide"
    persona_service.edit.assert_called_once_with(
        original.id, replacement, original.revision
    )
    assert app.session_state["characters_persona_id"] == original.id


def test_frozen_persona_explains_and_duplicates_edited_values(
    persona_service: Mock,
) -> None:
    """Keep history immutable while allowing a customized independent copy.

    Args:
        persona_service:
            Persona service double.
    """

    source = cast(Persona, persona_service.list.return_value[0]).model_copy(
        update={"is_frozen": True}
    )
    persona_service.list.return_value[0] = source
    duplicate_id = uuid4()

    def copy(persona_id: object, core: PersonaCore) -> Persona:
        """Expose the customized duplicate to the following rerun.

        Args:
            persona_id:
                Source persona identifier.
            core:
                Revised copied fields.

        Returns:
            Independent editable persona snapshot.
        """

        duplicate = Persona(id=duplicate_id, core=core)
        persona_service.list.return_value.append(duplicate)
        return duplicate

    persona_service.duplicate.side_effect = copy
    app = AppTest.from_function(_render).run()
    assert "rewrite that history" in app.info[0].value
    next(field for field in app.text_input if field.label == "Persona name").set_value(
        "Alternate"
    )
    next(
        button for button in app.button if button.label == "Duplicate persona"
    ).click().run()

    assert not app.exception
    revised_core = persona_service.duplicate.call_args.args[1]
    assert revised_core.name == "Alternate"
    persona_service.duplicate.assert_called_once_with(source.id, revised_core)
    persona_service.edit.assert_not_called()
    assert app.session_state["characters_persona_id"] == duplicate_id


@pytest.mark.parametrize(
    "error",
    [
        FrozenPersonaError("Duplicate this frozen persona to edit it"),
        StalePersonaError("Reload the persona before editing"),
    ],
)
def test_concurrent_edit_conflict_is_visible(
    persona_service: Mock, error: ValueError
) -> None:
    """Surface a freeze or stale revision racing with an editable submission.

    Args:
        persona_service:
            Persona service double.
        error:
            Concurrent service failure to present.
    """

    persona_service.edit.side_effect = error
    app = AppTest.from_function(_render).run()
    next(
        button for button in app.button if button.label == "Save changes"
    ).click().run()

    assert not app.exception
    assert str(error) in app.error[0].value
