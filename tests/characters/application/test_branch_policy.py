"""Mode-specific in-place and fork-required branching policy."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.application import decide_branch_mode
from chat_buddy.characters.domain import (
    BranchModeFacts,
    ContinuityMode,
    ConversationScope,
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
