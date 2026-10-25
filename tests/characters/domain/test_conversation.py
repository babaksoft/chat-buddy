"""Immutable message input and conversation selection validation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    ContinuityMode,
    ConversationScope,
    ConversationSettings,
    ConversationTarget,
    SubmittedInput,
)


@pytest.mark.parametrize("content", ["", " \n\t", "X" * 32769])
def test_invalid_submitted_input_is_rejected(content: str) -> None:
    """Reject blank and oversized input before any persistence.

    Args:
        content:
            Invalid authored input.
    """

    with pytest.raises(ValidationError):
        SubmittedInput(content=content)


def test_submitted_input_preserves_text_and_is_immutable() -> None:
    """Retain exact meaningful whitespace in an immutable value."""

    submitted = SubmittedInput(content="  Hi\n")
    assert submitted.content == "  Hi\n"
    with pytest.raises(ValidationError):
        submitted.content = "Changed"


def test_requested_selection_enforces_purpose_specific_limits() -> None:
    """Reject provider/model selections exceeding bounded authored values."""

    with pytest.raises(ValidationError):
        ConversationSettings(provider="X" * 65, model="model")
    with pytest.raises(ValidationError):
        ConversationSettings(provider="fake", model="X" * 257)


def test_mode_owned_target_requires_exact_scene_shape() -> None:
    """Require Storyline scene ownership while keeping Ongoing scene-free."""

    scope = ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )
    ongoing = ConversationTarget(scope=scope, mode=ContinuityMode.ONGOING)
    storyline = ConversationTarget(
        scope=scope, mode=ContinuityMode.STORYLINE, scene_id=uuid4()
    )

    assert ongoing.scene_id is None
    assert storyline.scene_id is not None
    with pytest.raises(ValidationError):
        ConversationTarget(scope=scope, mode=ContinuityMode.ONGOING, scene_id=uuid4())
    with pytest.raises(ValidationError):
        ConversationTarget(scope=scope, mode=ContinuityMode.STORYLINE)
    with pytest.raises(ValidationError):
        ConversationTarget(scope=scope, mode=ContinuityMode.TIMELINE)
