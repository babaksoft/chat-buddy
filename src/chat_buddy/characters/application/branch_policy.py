"""Pure mode-specific branch authorization."""

from typing import Literal
from uuid import UUID

from chat_buddy.characters.domain import (
    BranchDecision,
    BranchModeFacts,
    BranchModeFactsResolver,
    ContinuityMode,
    ConversationScope,
)


class DeferredBranchModeFactsResolver(BranchModeFactsResolver):
    """Resolve Ongoing facts while leaving future-mode facts unavailable."""

    def resolve(
        self,
        scope: ConversationScope,
        source_message_id: UUID,
        mode: ContinuityMode,
    ) -> BranchModeFacts:
        """Return exact references and no unimplemented mode-specific facts.

        Args:
            scope:
                Exact source conversation references.
            source_message_id:
                Exact persona response governing the action.
            mode:
                Persisted continuity mode.

        Returns:
            Ongoing authorization facts or fail-closed future-mode facts.
        """

        return BranchModeFacts(
            scope=scope,
            source_message_id=source_message_id,
            mode=mode,
        )


def decide_branch_mode(facts: BranchModeFacts) -> BranchDecision:
    """Authorize in-place branching or require a future mode fork.

    Args:
        facts:
            Persistence-neutral mode state and exact source references.

    Returns:
        Fail-closed branching decision.
    """

    disposition: Literal["in_place", "fork_required"] = "fork_required"
    reason: Literal[
        "ongoing",
        "latest_storyline_scene",
        "older_storyline_scene",
        "open_timeline_day",
        "closed_timeline_day",
        "missing_or_contradictory_mode_facts",
    ] = "missing_or_contradictory_mode_facts"

    if (
        facts.mode == ContinuityMode.ONGOING
        and facts.storyline_has_later_scenes is None
        and facts.timeline_day_closed is None
    ):
        disposition = "in_place"
        reason = "ongoing"
    elif (
        facts.mode == ContinuityMode.STORYLINE
        and facts.storyline_has_later_scenes is not None
        and facts.timeline_day_closed is None
    ):
        if facts.storyline_has_later_scenes:
            reason = "older_storyline_scene"
        else:
            disposition = "in_place"
            reason = "latest_storyline_scene"
    elif (
        facts.mode == ContinuityMode.TIMELINE
        and facts.timeline_day_closed is not None
        and facts.storyline_has_later_scenes is None
    ):
        if facts.timeline_day_closed:
            reason = "closed_timeline_day"
        else:
            disposition = "in_place"
            reason = "open_timeline_day"

    return BranchDecision(
        disposition=disposition,
        scope=facts.scope,
        source_message_id=facts.source_message_id,
        reason=reason,
    )
