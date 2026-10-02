"""Ongoing rolling-summary value invariants."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    CompletedTurn,
    ConversationScope,
    EffectiveGeneration,
    GenerationConfiguration,
    Message,
    ModelDescriptor,
    SummaryRevision,
)


def test_summary_values_are_immutable_and_require_persona_checkpoints() -> None:
    """Reject malformed turn pairs and summary lineage provenance."""

    scope = ConversationScope(
        identity_id=uuid4(),
        persona_id=uuid4(),
        continuity_id=uuid4(),
        conversation_id=uuid4(),
    )
    user = _message(scope, 1, "user")
    persona = _message(scope, 2, "persona")
    turn = CompletedTurn(user=user, persona=persona)
    assert turn.persona.sequence == 2
    with pytest.raises(ValidationError):
        CompletedTurn(user=persona, persona=user)
    generation = EffectiveGeneration(
        model=ModelDescriptor(
            provider="fake",
            model="summary",
            context_tokens=512,
            output_tokens=64,
            capabilities=frozenset({"summary"}),
        ),
        configuration=GenerationConfiguration(max_output_tokens=64),
        capability="summary",
        input_tokens=448,
    )
    summary = SummaryRevision(
        id=uuid4(),
        scope=scope,
        revision=1,
        predecessor_id=None,
        checkpoint_message_id=persona.id,
        checkpoint_sequence=2,
        content="A concise summary.",
        generation=generation,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        summary.content = "Changed"
    with pytest.raises(ValidationError):
        SummaryRevision.model_validate(
            summary.model_copy(update={"checkpoint_sequence": 1}).model_dump()
        )


def _message(
    scope: ConversationScope,
    sequence: int,
    role: Literal["user", "persona"],
) -> Message:
    """Build one test message.

    Args:
        scope:
            Shared ownership.
        sequence:
            Path position.
        role:
            User or persona role.

    Returns:
        Validated immutable message.
    """

    return Message(
        id=uuid4(),
        scope=scope,
        sequence=sequence,
        role=role,
        content=role,
        created_at=datetime.now(UTC),
    )
