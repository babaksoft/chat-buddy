"""Acceptance tests for Storyline navigation and scene management."""

from collections.abc import Generator
from typing import cast
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ContinuityLifecycle,
    ConversationScope,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    ResponseStyleSnapshot,
    Scene,
    SceneAppendEligibility,
    SceneDetails,
    SceneSequence,
    StaleStorylineError,
    StartAvailability,
    StartingOrigins,
    StartingRelationship,
    Storyline,
    StorylineGroup,
)
from chat_buddy.characters.ui import storylines_page


def _render() -> None:
    """Render only the focused Storylines page."""

    from chat_buddy.characters.ui import render_storylines_page

    render_storylines_page()


@pytest.fixture
def services() -> Generator[tuple[Mock, Mock, Mock, list[SceneSequence]], None, None]:
    """Provide profile and Storyline lifecycle doubles.

    Yields:
        Services and active plus archived scene sequences.
    """

    identity = Identity(
        id=uuid4(), details=IdentityDetails(name="You"), is_default=True
    )
    persona = Persona(id=uuid4(), core=PersonaCore(name="Guide", definition="Helpful"))
    active = _sequence(identity.id, persona.id, ContinuityLifecycle.ACTIVE)
    archived = _sequence(identity.id, persona.id, ContinuityLifecycle.ARCHIVED)
    identities = Mock(spec=IdentityService)
    personas = Mock(spec=PersonaService)
    storylines = Mock(spec=StorylineService)
    identities.ensure_default.return_value = identity
    identities.list.return_value = [identity]
    personas.list.return_value = [persona]
    storylines.list_grouped.return_value = (
        StorylineGroup(
            identity_id=identity.id,
            persona_id=persona.id,
            storylines=(active.storyline, archived.storyline),
        ),
    )
    storylines.start_availability.return_value = StartAvailability(
        can_start=False, reason="Archive the active Storyline before starting another."
    )
    storylines.resume.side_effect = lambda identity_id, persona_id, storyline_id: next(
        sequence
        for sequence in (active, archived)
        if (
            sequence.storyline.identity_id,
            sequence.storyline.persona_id,
            sequence.storyline.id,
        )
        == (identity_id, persona_id, storyline_id)
    )
    storylines.append_eligibility.side_effect = lambda *args: _eligibility(active)
    with (
        patch.object(
            storylines_page,
            "create_storyline_services",
            return_value=(identities, personas, storylines),
        ),
        patch.object(storylines_page, "render_conversation"),
        patch.object(storylines_page, "create_conversation_service"),
        patch.object(storylines_page, "create_storyline_fork_service"),
        patch.object(storylines_page, "_navigate_to_new_storyline") as navigate,
    ):
        storylines.navigate = navigate
        yield identities, personas, storylines, [active, archived]


def test_navigation_separates_active_and_archived_and_uses_complete_scope(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Expose both lifecycle groups and resume only by full ownership.

    Args:
        services:
            Storyline services and sequences.
    """

    storylines, sequences = services[2], services[3]
    selected = sequences[0]
    app = AppTest.from_function(_render).run()
    assert any(item.value == "Active" for item in app.sidebar.caption)
    assert any(item.value == "Archived" for item in app.sidebar.caption)
    app.button(key=f"characters_select_storyline_{selected.storyline.id}").click().run()

    scope = (
        selected.storyline.identity_id,
        selected.storyline.persona_id,
        selected.storyline.id,
    )
    assert app.session_state["characters_storyline_scope"] == scope
    storylines.resume.assert_called_with(*scope)
    assert app.session_state["characters_scene_id"] == selected.scenes[-1].id


def test_foreign_scope_is_cleared_without_resume(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Reject a Storyline identifier paired with foreign owners.

    Args:
        services:
            Storyline services and sequences.
    """

    storylines, sequence = services[2], services[3][0]
    app = AppTest.from_function(_render)
    app.session_state["characters_storyline_scope"] = (
        uuid4(),
        sequence.storyline.persona_id,
        sequence.storyline.id,
    )
    app.session_state["characters_scene_id"] = sequence.scenes[0].id
    app.run()

    assert "characters_storyline_scope" not in app.session_state
    assert "characters_scene_id" not in app.session_state
    storylines.resume.assert_not_called()


def test_incomplete_latest_scene_disables_append_with_guidance(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Prevent scene pre-creation until one complete exchange exists.

    Args:
        services:
            Storyline services and sequences.
    """

    storylines, active = services[2], services[3][0]
    storylines.append_eligibility.side_effect = None
    storylines.append_eligibility.return_value = _eligibility(active, complete=False)
    app = _selected_app(active)

    button = next(button for button in app.button if button.label == "Next scene")
    assert button.disabled
    assert button.help == "Complete one exchange before adding the next scene."
    storylines.append_next.assert_not_called()


def test_eligible_next_scene_is_appended_once_and_selected(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Append one reviewed scene and avoid replay after rerun.

    Args:
        services:
            Storyline services and sequences.
    """

    storylines, active = services[2], services[3][0]
    next_scene = _scene(active.storyline, 2, locked=False)
    completed_scene = active.scenes[0].model_copy(update={"setup_locked": True})
    updated = SceneSequence(
        storyline=active.storyline.model_copy(update={"revision": 2}),
        scenes=(completed_scene, next_scene),
    )

    def append(
        details: SceneDetails, eligibility: SceneAppendEligibility
    ) -> SceneSequence:
        """Expose the committed sequence on the following page rerun.

        Args:
            details:
                Submitted scene details.
            eligibility:
                Submitted append guards.

        Returns:
            Updated sequence.
        """

        storylines.resume.side_effect = lambda *args: updated
        return updated

    storylines.append_next.side_effect = append
    app = _selected_app(active)
    next_title = next(
        item for item in app.text_input if item.label == "Next scene title"
    )
    next_setup = next(
        item for item in app.text_area if item.label == "Next scene setup"
    )
    next_title.set_value("Departure")
    next_setup.set_value("The train begins to move.")
    next(button for button in app.button if button.label == "Next scene").click().run()

    storylines.append_next.assert_called_once()
    details, eligibility = storylines.append_next.call_args.args
    assert details.title == "Departure"
    assert eligibility.can_append
    assert app.session_state["characters_scene_id"] == next_scene.id
    app.run()
    storylines.append_next.assert_called_once()


def test_scene_title_and_unlocked_setup_use_revision_guards(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Submit mutable scene fields with complete ownership and revision.

    Args:
        services:
            Storyline services and sequences.
    """

    storylines, active = services[2], services[3][0]
    app = _selected_app(active)
    scene = active.scenes[-1]
    title = next(item for item in app.text_input if item.label == "Scene title")
    title.set_value("Renamed arrival")
    next(
        button for button in app.button if button.label == "Rename scene"
    ).click().run()
    storylines.rename_scene.assert_called_once_with(
        scene.scope, scene.id, "Renamed arrival", active.storyline.revision
    )

    app = _selected_app(active)
    setup = next(item for item in app.text_area if item.label == "Scene setup")
    setup.set_value("A brighter station.")
    next(button for button in app.button if button.label == "Save setup").click().run()
    storylines.replace_scene_setup.assert_called_once_with(
        scene.scope, scene.id, "A brighter station.", active.storyline.revision
    )


def test_archive_stale_revision_is_visible_and_archived_pair_can_start_replacement(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Surface stale archive writes and release an archived pair's start action.

    Args:
        services:
            Storyline services and sequences.
    """

    storylines, active, archived = services[2], *services[3]
    storylines.archive.side_effect = StaleStorylineError("stale")
    app = _selected_app(active)
    app.button(key=f"characters_archive_{active.storyline.id}").click().run()
    assert any("changed" in item.value for item in app.warning)

    storylines.archive.side_effect = None
    storylines.list_grouped.return_value = (
        StorylineGroup(
            identity_id=archived.storyline.identity_id,
            persona_id=archived.storyline.persona_id,
            storylines=(archived.storyline,),
        ),
    )
    storylines.start_availability.return_value = StartAvailability(can_start=True)
    app = AppTest.from_function(_render).run()
    button = app.button(
        key=(
            f"characters_new_storyline_{archived.storyline.identity_id}_"
            f"{archived.storyline.persona_id}"
        )
    )
    assert not button.disabled
    button.click().run()
    storylines.navigate.assert_called_once_with()


def test_selected_scene_conversation_uses_exact_target_and_scene_write_policy(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Route latest and historical scenes through mode-owned conversation targets.

    Args:
        services:
            Storyline services and sequences.
    """

    active = services[3][0]
    latest = _scene(active.storyline, 2, locked=False)
    sequence = SceneSequence(
        storyline=active.storyline.model_copy(update={"revision": 2}),
        scenes=(active.scenes[0].model_copy(update={"setup_locked": True}), latest),
    )
    services[2].resume.side_effect = lambda *args: sequence
    app = _selected_app(sequence)

    rendered = cast(Mock, storylines_page.render_conversation)
    call = rendered.call_args
    target = call.args[1]
    assert target.scope == latest.scope
    assert target.scene_id == latest.id
    assert target.mode == "storyline"
    assert call.args[3] is False
    assert call.kwargs["read_only"] is False

    app.button(key=f"characters_select_scene_{sequence.scenes[0].id}").click().run()
    call = rendered.call_args
    assert call.args[1].scene_id == sequence.scenes[0].id
    assert call.kwargs["read_only"] is True


def test_fork_preview_duplicates_exactly_one_profile_with_observed_guards(
    services: tuple[Mock, Mock, Mock, list[SceneSequence]],
) -> None:
    """Prepare a named fork from exact source revision, branch point, and leaf.

    Args:
        services:
            Storyline services and sequences.
    """

    from datetime import UTC, datetime

    from chat_buddy.characters.domain import (
        ContinuityMode,
        ConversationGraphView,
        ConversationTarget,
        GraphNodeView,
        Identity,
        IdentityDetails,
        MessageNode,
    )

    identities, personas, _, sequences = services
    sequence = sequences[0]
    scene = sequence.scenes[0]
    leaf_id = uuid4()
    node = MessageNode.model_construct(
        id=leaf_id,
        scope=scene.scope,
        parent_id=uuid4(),
        role="persona",
        content="A saved answer",
        created_at=datetime.now(UTC),
    )
    view = GraphNodeView.model_construct(
        message=node,
        alternative_ids=(node.id,),
        retry_count=0,
        selected=True,
        selected_leaf=True,
        branchable=True,
    )
    graph = ConversationGraphView.model_construct(
        scope=scene.scope, selected_leaf_id=leaf_id, nodes=(view,)
    )
    duplicate = Identity(
        id=uuid4(), details=IdentityDetails(name="You"), is_default=False
    )
    identities.duplicate.return_value = duplicate
    forks = Mock()
    preview = Mock()
    forks.preview.return_value = preview
    target = ConversationTarget(
        scope=scene.scope, mode=ContinuityMode.STORYLINE, scene_id=scene.id
    )

    result = storylines_page._prepare_fork_preview(
        forks,
        identities,
        personas,
        sequence,
        target,
        graph,
        view,
        "A different road",
        "Identity",
    )

    assert result is preview
    identities.duplicate.assert_called_once_with(sequence.storyline.identity_id)
    personas.duplicate.assert_not_called()
    call = forks.preview.call_args.kwargs
    assert call["name"] == "A different road"
    assert call["target"] == target
    assert call["branch_point_message_id"] == node.id
    assert call["expected_selected_leaf_id"] == leaf_id
    assert call["expected_storyline_revision"] == sequence.storyline.revision
    assert call["target_identity_id"] == duplicate.id
    assert call["target_persona_id"] == sequence.storyline.persona_id


def _selected_app(sequence: SceneSequence) -> AppTest:
    """Render with one complete Storyline selection.

    Args:
        sequence:
            Sequence to select.

    Returns:
        Executed selected Storyline page.
    """

    storyline = sequence.storyline
    app = AppTest.from_function(_render)
    app.session_state["characters_storyline_scope"] = (
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
    )
    return app.run()


def _sequence(
    identity_id: UUID, persona_id: UUID, lifecycle: ContinuityLifecycle
) -> SceneSequence:
    """Create a one-scene Storyline sequence.

    Args:
        identity_id:
            Identity owner.
        persona_id:
            Persona owner.
        lifecycle:
            Active or archived state.

    Returns:
        Complete detached sequence.
    """

    storyline = Storyline(
        id=uuid4(),
        identity_id=identity_id,
        persona_id=persona_id,
        name="Long Road" if lifecycle == ContinuityLifecycle.ACTIVE else "Old Road",
        lifecycle=lifecycle,
        relationship=_relationship(),
        revision=1,
    )
    return SceneSequence(
        storyline=storyline,
        scenes=(
            _scene(storyline, 1, locked=lifecycle == ContinuityLifecycle.ARCHIVED),
        ),
    )


def _scene(storyline: Storyline, position: int, *, locked: bool) -> Scene:
    """Create one owned scene.

    Args:
        storyline:
            Owning Storyline.
        position:
            Immutable chronological position.
        locked:
            Whether setup is frozen.

    Returns:
        Owned scene snapshot.
    """

    return Scene(
        id=uuid4(),
        scope=ConversationScope(
            identity_id=storyline.identity_id,
            persona_id=storyline.persona_id,
            continuity_id=storyline.id,
            conversation_id=uuid4(),
        ),
        position=position,
        details=SceneDetails(
            title="Arrival" if position == 1 else "Departure",
            setup="A quiet station at dusk.",
            response_style=ResponseStyleSnapshot(
                name="storyline.default",
                version="1.0.0",
                instruction="Respond naturally within the current scene.",
            ),
        ),
        setup_locked=locked,
    )


def _eligibility(
    sequence: SceneSequence, *, complete: bool = True
) -> SceneAppendEligibility:
    """Create append facts for the sequence's latest scene.

    Args:
        sequence:
            Current Storyline sequence.
        complete:
            Whether a complete selected exchange exists.

    Returns:
        Valid append eligibility snapshot.
    """

    latest = sequence.scenes[-1]
    return SceneAppendEligibility(
        storyline_id=sequence.storyline.id,
        scene_id=latest.id,
        expected_storyline_revision=sequence.storyline.revision,
        expected_selected_leaf_id=uuid4() if complete else None,
        scene_position=latest.position,
        storyline_lifecycle=sequence.storyline.lifecycle,
        is_latest_scene=True,
        has_complete_selected_exchange=complete,
        has_unmatched_input=False,
        has_open_attempt=False,
    )


def _relationship() -> StartingRelationship:
    """Create the resolved default relationship.

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
