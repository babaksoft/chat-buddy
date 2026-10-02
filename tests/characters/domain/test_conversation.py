"""Immutable message input and conversation selection validation."""

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    ConversationSettings,
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
