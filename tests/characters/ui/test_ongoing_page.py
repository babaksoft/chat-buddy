"""Service-double acceptance tests for focused Ongoing navigation."""

from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import (
    Continuity,
    ContinuityGroup,
    ContinuityLifecycle,
    ContinuityMode,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    StartAvailability,
    StartingOrigins,
    StartingRelationship,
)
from chat_buddy.characters.ui import ongoing_page


def _render() -> None:
    """Render only the focused Ongoing page."""

    from chat_buddy.characters.ui import render_ongoing_page

    render_ongoing_page()


@pytest.fixture
def ongoing_services() -> (
    Generator[tuple[Mock, Mock, Mock, list[Continuity]], None, None]
):
    """Provide profiles, grouped histories, and lifecycle operations.

    Yields:
        Service doubles and all persisted continuity snapshots.
    """

    identities = [
        Identity(id=uuid4(), details=IdentityDetails(name="You"), is_default=True),
        Identity(id=uuid4(), details=IdentityDetails(name="Traveler")),
    ]
    personas = [
        Persona(id=uuid4(), core=PersonaCore(name="Guide", definition="Helpful")),
        Persona(id=uuid4(), core=PersonaCore(name="Friend", definition="Warm")),
    ]
    rows = [
        _continuity(identities[0].id, personas[0].id),
        _continuity(
            identities[0].id,
            personas[0].id,
            lifecycle=ContinuityLifecycle.ARCHIVED,
        ),
        _continuity(identities[1].id, personas[1].id),
    ]
    identity_service = Mock(spec=IdentityService)
    persona_service = Mock(spec=PersonaService)
    continuity_service = Mock(spec=ContinuityService)
    identity_service.ensure_default.return_value = identities[0]
    identity_service.list.return_value = identities
    persona_service.list.return_value = personas
    continuity_service.list_grouped.return_value = (
        ContinuityGroup(
            identity_id=identities[0].id,
            persona_id=personas[0].id,
            continuities=(rows[0], rows[1]),
        ),
        ContinuityGroup(
            identity_id=identities[1].id,
            persona_id=personas[1].id,
            continuities=(rows[2],),
        ),
    )
    continuity_service.start_availability.return_value = StartAvailability(
        can_start=True
    )
    continuity_service.resume.side_effect = (
        lambda identity_id, persona_id, row_id: next(
            row
            for row in rows
            if (row.identity_id, row.persona_id, row.id)
            == (identity_id, persona_id, row_id)
        )
    )
    with (
        patch.object(
            ongoing_page,
            "create_ongoing_services",
            return_value=(identity_service, persona_service, continuity_service),
        ),
        patch.object(ongoing_page, "render_ongoing") as conversation,
    ):
        continuity_service.conversation = conversation
        yield identity_service, persona_service, continuity_service, rows


def test_renders_every_profile_pair_and_continuity(
    ongoing_services: tuple[Mock, Mock, Mock, list[Continuity]],
) -> None:
    """Expose the complete identity, persona, and history hierarchy.

    Args:
        ongoing_services:
            Ongoing application doubles and snapshots.
    """

    identities, personas, continuities, rows = ongoing_services
    app = AppTest.from_function(_render).run()

    assert not app.exception
    assert app.title[0].value == "💞 Ongoing"
    assert {expander.label for expander in app.sidebar.expander} == {
        "You",
        "Traveler",
    }
    for row in rows:
        assert app.button(key=f"characters_select_{row.id}")
    for identity in identities.list.return_value:
        for persona in personas.list.return_value:
            assert app.button(key=f"characters_new_ongoing_{identity.id}_{persona.id}")
    assert {call.args for call in continuities.start_availability.call_args_list} == {
        (identity.id, persona.id)
        for identity in identities.list.return_value
        for persona in personas.list.return_value
    }


def test_selection_stores_and_resumes_complete_scope(
    ongoing_services: tuple[Mock, Mock, Mock, list[Continuity]],
) -> None:
    """Select a continuity with all owners before rendering its conversation.

    Args:
        ongoing_services:
            Ongoing application doubles and snapshots.
    """

    _, _, continuities, rows = ongoing_services
    selected = rows[2]
    app = AppTest.from_function(_render).run()
    app.button(key=f"characters_select_{selected.id}").click().run()

    assert not app.exception
    assert app.session_state["characters_continuity_scope"] == (
        selected.identity_id,
        selected.persona_id,
        selected.id,
    )
    assert app.session_state["characters_identity_id"] == selected.identity_id
    assert app.session_state["characters_persona_id"] == selected.persona_id
    assert app.session_state["characters_continuity_id"] == selected.id
    continuities.resume.assert_called_with(
        selected.identity_id, selected.persona_id, selected.id
    )
    continuities.conversation.assert_called_with(selected)


def test_cross_owner_scope_is_cleared_without_resume(
    ongoing_services: tuple[Mock, Mock, Mock, list[Continuity]],
) -> None:
    """Reject a continuity identifier paired with different profile owners.

    Args:
        ongoing_services:
            Ongoing application doubles and snapshots.
    """

    identities, personas, continuities, rows = ongoing_services
    app = AppTest.from_function(_render)
    app.session_state["characters_continuity_scope"] = (
        identities.list.return_value[0].id,
        personas.list.return_value[0].id,
        rows[2].id,
    )
    app.session_state["characters_continuity_id"] = rows[2].id
    app.run()

    assert not app.exception
    assert "characters_continuity_scope" not in app.session_state
    assert "characters_continuity_id" not in app.session_state
    continuities.resume.assert_not_called()
    continuities.conversation.assert_not_called()


def test_each_pair_has_available_or_reasoned_disabled_start(
    ongoing_services: tuple[Mock, Mock, Mock, list[Continuity]],
) -> None:
    """Use application availability to enable or explain each pair action.

    Args:
        ongoing_services:
            Ongoing application doubles and snapshots.
    """

    identities, personas, continuities, _ = ongoing_services
    blocked = (identities.list.return_value[0].id, personas.list.return_value[0].id)

    def availability(identity_id: UUID, persona_id: UUID) -> StartAvailability:
        """Block only the pair with an active Ongoing.

        Args:
            identity_id:
                Pair identity.
            persona_id:
                Pair persona.

        Returns:
            Pair-specific start availability.
        """

        if (identity_id, persona_id) == blocked:
            return StartAvailability(
                can_start=False,
                reason="Archive the active Ongoing before starting another.",
            )
        return StartAvailability(can_start=True)

    continuities.start_availability.side_effect = availability
    app = AppTest.from_function(_render).run()
    blocked_button = app.button(key=f"characters_new_ongoing_{blocked[0]}_{blocked[1]}")
    available = (
        identities.list.return_value[1].id,
        personas.list.return_value[0].id,
    )
    available_button = app.button(
        key=f"characters_new_ongoing_{available[0]}_{available[1]}"
    )

    assert blocked_button.disabled
    assert blocked_button.help == "Archive the active Ongoing before starting another."
    assert any("Archive the active Ongoing" in item.value for item in app.caption)
    assert not available_button.disabled
    available_button.click().run()
    assert app.session_state["characters_identity_id"] == available[0]
    assert app.session_state["characters_persona_id"] == available[1]
    assert app.session_state["characters_start_requested"]
    assert app.success[0].value.startswith("Pair selected")


@pytest.mark.parametrize(
    "lifecycle", [ContinuityLifecycle.ACTIVE, ContinuityLifecycle.ARCHIVED]
)
def test_active_can_archive_and_archived_is_read_only(
    ongoing_services: tuple[Mock, Mock, Mock, list[Continuity]],
    lifecycle: ContinuityLifecycle,
) -> None:
    """Allow archival only for active histories and retain archived chat access.

    Args:
        ongoing_services:
            Ongoing application doubles and snapshots.
        lifecycle:
            Selected continuity lifecycle.
    """

    _, _, continuities, rows = ongoing_services
    selected = next(row for row in rows if row.lifecycle == lifecycle)
    app = AppTest.from_function(_render)
    app.session_state["characters_continuity_scope"] = (
        selected.identity_id,
        selected.persona_id,
        selected.id,
    )
    app.run()

    assert not app.exception
    continuities.conversation.assert_called_once_with(selected)
    if lifecycle == ContinuityLifecycle.ARCHIVED:
        assert any("read-only" in item.value for item in app.info)
        assert not any(button.label == "Archive Ongoing" for button in app.button)
        return
    app.button(key="characters_archive").click().run()
    continuities.archive.assert_called_once_with(
        selected.identity_id, selected.persona_id, selected.id
    )


def _continuity(
    identity_id: UUID,
    persona_id: UUID,
    lifecycle: ContinuityLifecycle = ContinuityLifecycle.ACTIVE,
) -> Continuity:
    """Build a detached Ongoing snapshot.

    Args:
        identity_id:
            Identity owner.
        persona_id:
            Persona owner.
        lifecycle:
            Active or archived state.

    Returns:
        Complete continuity snapshot.
    """

    return Continuity(
        id=uuid4(),
        identity_id=identity_id,
        persona_id=persona_id,
        mode=ContinuityMode.ONGOING,
        lifecycle=lifecycle,
        conversation_id=uuid4(),
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
    )
