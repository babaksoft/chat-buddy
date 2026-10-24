"""Executable Storyline and ordered-scene domain contracts."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    ContinuityLifecycle,
    ConversationScope,
    RelationshipIntent,
    RelationshipSelection,
    ResponseStyleSnapshot,
    Scene,
    SceneAppendEligibility,
    SceneDetails,
    SceneSequence,
    StartingOrigins,
    StartingRelationship,
    StartStoryline,
    Storyline,
    StorylineForkSource,
    StorylineGroup,
    StorylineModeAction,
)


def _relationship() -> StartingRelationship:
    """Create a valid resolved starting relationship.

    Returns:
        Immutable starting relationship fixture.
    """

    return StartingRelationship(
        intent=RelationshipIntent.PLATONIC,
        social="stranger",
        romantic="none",
        dynamic="neutral",
        trust="unknown",
        affection="neutral",
        boundaries=("no_romance",),
        origins=StartingOrigins(
            social="default",
            romantic="default",
            dynamic="default",
            trust="default",
            affection="default",
            boundaries="user_selected",
        ),
    )


def _style() -> ResponseStyleSnapshot:
    """Create the fixed Stage 6 response style fixture.

    Returns:
        Valid immutable response-style snapshot.
    """

    return ResponseStyleSnapshot(
        name="storyline.default",
        version="1.0.0",
        instruction="Respond naturally within the current scene.",
    )


def _storyline(
    *,
    identity_id: UUID | None = None,
    persona_id: UUID | None = None,
    lifecycle: ContinuityLifecycle = ContinuityLifecycle.ACTIVE,
) -> Storyline:
    """Create a valid Storyline fixture.

    Args:
        identity_id:
            Optional stable identity owner.
        persona_id:
            Optional stable persona owner.
        lifecycle:
            Desired lifecycle state.

    Returns:
        Immutable Storyline snapshot.
    """

    return Storyline(
        id=uuid4(),
        identity_id=identity_id or uuid4(),
        persona_id=persona_id or uuid4(),
        name="The Long Road",
        lifecycle=lifecycle,
        relationship=_relationship(),
        revision=1,
    )


def _scene(storyline: Storyline, position: int, *, locked: bool = True) -> Scene:
    """Create one owned scene fixture.

    Args:
        storyline:
            Owning Storyline.
        position:
            Immutable chronological position.
        locked:
            Whether setup has frozen.

    Returns:
        Owned immutable scene.
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
            title=f"Scene {position}",
            setup="A quiet station at dusk.",
            response_style=_style(),
        ),
        setup_locked=locked,
    )


def _fork_source(position: int = 1) -> StorylineForkSource:
    """Create an exact guarded fork source.

    Args:
        position:
            Immutable source scene position.

    Returns:
        Valid source point.
    """

    return StorylineForkSource(
        scene_id=uuid4(),
        scope=ConversationScope(
            identity_id=uuid4(),
            persona_id=uuid4(),
            continuity_id=uuid4(),
            conversation_id=uuid4(),
        ),
        scene_position=position,
        expected_storyline_revision=3,
        expected_selected_leaf_id=uuid4(),
        source_message_id=uuid4(),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", " "),
        ("name", "n" * 129),
        ("title", " "),
        ("title", "t" * 129),
        ("setup", " "),
        ("setup", "s" * 8193),
    ],
)
def test_authored_storyline_fields_enforce_bounds(field: str, value: str) -> None:
    """Reject blank or oversized names, titles, and setups.

    Args:
        field:
            Authored field under test.
        value:
            Invalid authored content.
    """

    scene_values = {
        "title": "Arrival",
        "setup": "They meet beside a train.",
        "response_style": _style(),
    }
    if field in scene_values:
        scene_values[field] = value
        with pytest.raises(ValidationError):
            SceneDetails.model_validate(scene_values)
        return

    storyline = _storyline()
    with pytest.raises(ValidationError):
        storyline.model_copy(update={field: value}).__class__.model_validate(
            {**storyline.model_dump(), field: value}
        )


def test_confirmed_start_and_snapshots_are_immutable() -> None:
    """Freeze every reviewed start input and persisted domain snapshot."""

    details = SceneDetails(
        title="Arrival", setup="They meet beside a train.", response_style=_style()
    )
    request = StartStoryline(
        request_id=uuid4(),
        identity_id=uuid4(),
        persona_id=uuid4(),
        identity_revision=2,
        persona_revision=4,
        name="Railway Days",
        relationship=RelationshipSelection(intent=RelationshipIntent.PLATONIC),
        initial_scene=details,
    )
    storyline = _storyline(
        identity_id=request.identity_id, persona_id=request.persona_id
    )
    scene = _scene(storyline, 1, locked=False)

    for value, field, replacement in [
        (request, "name", "Changed"),
        (details, "setup", "Changed"),
        (storyline, "revision", 2),
        (scene, "position", 2),
    ]:
        with pytest.raises(ValidationError):
            setattr(value, field, replacement)


def test_group_allows_archived_replacement_but_rejects_two_active_storylines() -> None:
    """Model archival as releasing exactly one mode-specific active slot."""

    identity_id, persona_id = uuid4(), uuid4()
    archived = _storyline(
        identity_id=identity_id,
        persona_id=persona_id,
        lifecycle=ContinuityLifecycle.ARCHIVED,
    )
    replacement = _storyline(identity_id=identity_id, persona_id=persona_id)

    group = StorylineGroup(
        identity_id=identity_id,
        persona_id=persona_id,
        storylines=(archived, replacement),
    )
    assert group.storylines == (archived, replacement)

    with pytest.raises(ValidationError, match="at most one active"):
        StorylineGroup(
            identity_id=identity_id,
            persona_id=persona_id,
            storylines=(replacement, replacement.model_copy(update={"id": uuid4()})),
        )
    with pytest.raises(ValidationError, match="supplied pair"):
        StorylineGroup(
            identity_id=identity_id,
            persona_id=persona_id,
            storylines=(_storyline(),),
        )


def test_scene_sequence_requires_owned_consecutive_append_order() -> None:
    """Reject foreign scenes, gaps, reorderings, and unlocked older scenes."""

    storyline = _storyline()
    first, second = _scene(storyline, 1), _scene(storyline, 2, locked=False)
    assert (
        SceneSequence(storyline=storyline, scenes=(first, second)).scenes[-1] == second
    )

    invalid_sequences = [
        (second, first),
        (first, second.model_copy(update={"position": 3})),
        (first.model_copy(update={"setup_locked": False}), second),
        (first, _scene(_storyline(), 2)),
    ]
    for scenes in invalid_sequences:
        with pytest.raises(ValidationError):
            SceneSequence(storyline=storyline, scenes=scenes)


@pytest.mark.parametrize(
    ("changes", "can_append", "reason"),
    [
        ({}, True, None),
        ({"storyline_lifecycle": "archived"}, False, "archived_storyline"),
        ({"is_latest_scene": False}, False, "not_latest_scene"),
        (
            {"has_complete_selected_exchange": False},
            False,
            "no_complete_exchange",
        ),
        ({"has_unmatched_input": True}, False, "unmatched_input"),
        (
            {"has_unmatched_input": True, "has_open_attempt": True},
            False,
            "unmatched_input",
        ),
    ],
)
def test_next_scene_eligibility_is_derived_from_complete_idle_latest_scene(
    changes: dict[str, object], can_append: bool, reason: str | None
) -> None:
    """Cover every ordered append guard and its stable first failure.

    Args:
        changes:
            Facts overriding the eligible baseline.
        can_append:
            Expected authorization.
        reason:
            Expected first block reason.
    """

    values: dict[str, object] = {
        "storyline_id": uuid4(),
        "scene_id": uuid4(),
        "expected_storyline_revision": 2,
        "expected_selected_leaf_id": uuid4(),
        "scene_position": 1,
        "storyline_lifecycle": "active",
        "is_latest_scene": True,
        "has_complete_selected_exchange": True,
        "has_unmatched_input": False,
        "has_open_attempt": False,
    }
    eligibility = SceneAppendEligibility.model_validate({**values, **changes})
    assert eligibility.can_append is can_append
    assert eligibility.block_reason == reason


def test_open_attempt_requires_unmatched_selected_input() -> None:
    """Reject contradictory append facts before a repository sees them."""

    with pytest.raises(ValidationError, match="open attempt"):
        SceneAppendEligibility(
            storyline_id=uuid4(),
            scene_id=uuid4(),
            expected_storyline_revision=1,
            expected_selected_leaf_id=uuid4(),
            scene_position=1,
            storyline_lifecycle=ContinuityLifecycle.ACTIVE,
            is_latest_scene=True,
            has_complete_selected_exchange=True,
            has_unmatched_input=False,
            has_open_attempt=True,
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda source: {"latest_scene_position": 0},
        lambda source: {"latest_scene_position": source.scene_position - 1},
        lambda source: {
            "latest_scene_position": source.scene_position,
            "latest_scene_id": uuid4(),
        },
        lambda source: {
            "latest_scene_position": source.scene_position + 1,
            "latest_scene_id": source.scene_id,
        },
    ],
)
def test_storyline_mode_action_rejects_impossible_fork_inputs(
    change: Callable[[StorylineForkSource], dict[str, object]],
) -> None:
    """Validate exact source/latest relationships before branch policy.

    Args:
        change:
            Invalid latest-scene values.
    """

    source = _fork_source(position=2)
    values: dict[str, object] = {
        "source": source,
        "latest_scene_id": source.scene_id,
        "latest_scene_position": source.scene_position,
    }
    with pytest.raises(ValidationError):
        StorylineModeAction.model_validate({**values, **change(source)})


def test_fork_source_and_mode_action_are_exact_and_immutable() -> None:
    """Derive latest versus older status while retaining every source guard."""

    source = _fork_source(position=2)
    latest = StorylineModeAction(
        source=source,
        latest_scene_id=source.scene_id,
        latest_scene_position=2,
    )
    older = StorylineModeAction(
        source=source,
        latest_scene_id=uuid4(),
        latest_scene_position=3,
    )

    assert latest.has_later_scenes is False
    assert older.has_later_scenes is True
    with pytest.raises(ValidationError):
        source.expected_storyline_revision = 4
