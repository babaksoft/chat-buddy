"""Mode-specific in-place and fork-required branching policy."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.application import (
    DeferredBranchModeFactsResolver,
    decide_branch_mode,
)
from chat_buddy.characters.domain import (
    BranchModeFacts,
    ContinuityMode,
    ConversationScope,
    StorylineForkSource,
    StorylineModeAction,
)


def _scope() -> ConversationScope:
    """Create exact source references for policy results.

    Returns:
        Complete generated ownership scope.
    """

    return ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )


@pytest.mark.parametrize(
    ("mode", "storyline_later", "timeline_closed", "disposition", "reason"),
    [
        (ContinuityMode.ONGOING, None, None, "in_place", "ongoing"),
        (
            ContinuityMode.STORYLINE,
            False,
            None,
            "in_place",
            "latest_storyline_scene",
        ),
        (
            ContinuityMode.STORYLINE,
            True,
            None,
            "fork_required",
            "older_storyline_scene",
        ),
        (
            ContinuityMode.TIMELINE,
            None,
            False,
            "in_place",
            "open_timeline_day",
        ),
        (
            ContinuityMode.TIMELINE,
            None,
            True,
            "fork_required",
            "closed_timeline_day",
        ),
        (
            ContinuityMode.STORYLINE,
            None,
            None,
            "fork_required",
            "missing_or_contradictory_mode_facts",
        ),
        (
            ContinuityMode.TIMELINE,
            True,
            False,
            "fork_required",
            "missing_or_contradictory_mode_facts",
        ),
    ],
)
def test_mode_policy_is_explicit_and_fails_closed(
    mode: ContinuityMode,
    storyline_later: bool | None,
    timeline_closed: bool | None,
    disposition: str,
    reason: str,
) -> None:
    """Decide every current and future mode without future persistence models.

    Args:
        mode:
            Governing continuity mode.
        storyline_later:
            Optional dependent-scene fact.
        timeline_closed:
            Optional day-closure fact.
        disposition:
            Expected mutation location.
        reason:
            Expected stable policy explanation.
    """

    scope = _scope()
    source_message_id = uuid4()
    decision = decide_branch_mode(
        BranchModeFacts(
            scope=scope,
            source_message_id=source_message_id,
            mode=mode,
            storyline_has_later_scenes=storyline_later,
            timeline_day_closed=timeline_closed,
        )
    )
    assert decision.disposition == disposition
    assert decision.reason == reason
    assert decision.scope == scope
    assert decision.source_message_id == source_message_id
    with pytest.raises(ValidationError):
        decision.reason = "changed"  # type: ignore[assignment]


@pytest.mark.parametrize(
    ("mode", "storyline_later", "timeline_closed"),
    [
        (ContinuityMode.ONGOING, False, None),
        (ContinuityMode.ONGOING, None, False),
        (ContinuityMode.STORYLINE, False, False),
        (ContinuityMode.TIMELINE, True, False),
    ],
)
def test_mode_policy_rejects_every_contradictory_fact_shape(
    mode: ContinuityMode,
    storyline_later: bool | None,
    timeline_closed: bool | None,
) -> None:
    """Require only facts belonging to the persisted continuity mode.

    Args:
        mode:
            Governing continuity mode.
        storyline_later:
            Optional dependent-scene fact.
        timeline_closed:
            Optional day-closure fact.
    """

    decision = decide_branch_mode(
        BranchModeFacts(
            scope=_scope(),
            source_message_id=uuid4(),
            mode=mode,
            storyline_has_later_scenes=storyline_later,
            timeline_day_closed=timeline_closed,
        )
    )
    assert decision.disposition == "fork_required"
    assert decision.reason == "missing_or_contradictory_mode_facts"


def test_deferred_resolver_preserves_exact_references_and_fails_future_modes_closed() -> (
    None
):
    """Leave unimplemented Storyline and Timeline facts absent."""

    scope = _scope()
    source_message_id = uuid4()
    facts = DeferredBranchModeFactsResolver().resolve(
        scope, source_message_id, ContinuityMode.STORYLINE
    )
    decision = decide_branch_mode(facts)

    assert facts.scope == scope
    assert facts.source_message_id == source_message_id
    assert decision.disposition == "fork_required"
    assert decision.reason == "missing_or_contradictory_mode_facts"


@pytest.mark.parametrize(
    ("latest_position", "disposition", "reason"),
    [
        (2, "in_place", "latest_storyline_scene"),
        (3, "fork_required", "older_storyline_scene"),
    ],
)
def test_real_storyline_positions_drive_mode_policy_without_repository_guesses(
    latest_position: int, disposition: str, reason: str
) -> None:
    """Authorize latest scenes and require forks for older dependent scenes.

    Args:
        latest_position:
            Persisted position of the actual latest scene.
        disposition:
            Expected mutation location.
        reason:
            Expected stable policy reason.
    """

    scope = _scope()
    source_message_id = uuid4()
    scene_id = uuid4()
    action = StorylineModeAction(
        source=StorylineForkSource(
            scene_id=scene_id,
            scope=scope,
            scene_position=2,
            expected_storyline_revision=5,
            expected_selected_leaf_id=uuid4(),
            source_message_id=source_message_id,
        ),
        latest_scene_id=scene_id if latest_position == 2 else uuid4(),
        latest_scene_position=latest_position,
    )

    decision = decide_branch_mode(action)

    assert decision.disposition == disposition
    assert decision.reason == reason
    assert decision.scope == scope
    assert decision.source_message_id == source_message_id
