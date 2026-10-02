from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextAssemblyResult,
    ContextBudgeter,
    ContextEligibility,
    ContextInputs,
    GenerationConfiguration,
    MemoryLifecycle,
    ModelDescriptor,
)
from chat_buddy.chat.utils.fake_data import fake_memory, fake_summary

NOW = datetime(2026, 9, 18, tzinfo=UTC)


class FakeEligibility:
    """Eligibility fake that deliberately has no token counter."""

    def get_inputs(
        self, conversation_id: UUID, current_input: ChatMessage
    ) -> ContextInputs:
        """Return supplied current input as eligible context.

        Args:
            conversation_id:
                Conversation identifier supplied by the caller.
            current_input:
                Current user input supplied by the caller.

        Returns:
            Context inputs containing no repository-loaded components.
        """

        return ContextInputs(conversation_id, current_input)


class FakeBudgeter:
    """Budget fake that deliberately has no repository."""

    def assemble(
        self,
        inputs: ContextInputs,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> ContextAssemblyResult:
        """Assemble only the current input without querying persistence.

        Args:
            inputs:
                Eligible context inputs to assemble.
            model:
                Selected model, unused by this fake.
            configuration:
                Effective generation settings, unused by this fake.

        Returns:
            Single-message assembly result for the current input.
        """

        return ContextAssemblyResult((inputs.current_input,), 1, 1)


def _turn(conversation_id: UUID) -> CompletedTurn:
    """Create a valid completed turn for tests.

    Args:
        conversation_id:
            Owning conversation identifier.

    Returns:
        Valid completed turn.
    """

    return CompletedTurn(
        conversation_id=conversation_id,
        attempt_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        user_content="Hello",
        assistant_content="Hi",
        completed_at=NOW,
    )


def test_context_inputs_enforce_eligibility_and_conversation_ownership() -> None:
    """Persistence-neutral inputs reject cross-scope and inactive components."""

    conversation_id = uuid4()
    inputs = ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "Question"),
        memories=(fake_memory(),),
        summary=fake_summary(conversation_id),
        uncovered_turns=(_turn(conversation_id),),
    )
    assert len(inputs.uncovered_turns) == 1

    with pytest.raises(ValueError, match="another conversation"):
        ContextInputs(
            conversation_id=conversation_id,
            current_input=ChatMessage(ChatRole.USER, "Question"),
            summary=fake_summary(uuid4()),
        )
    with pytest.raises(ValueError, match="active memories"):
        ContextInputs(
            conversation_id=conversation_id,
            current_input=ChatMessage(ChatRole.USER, "Question"),
            memories=(fake_memory(MemoryLifecycle.EXCLUDED),),
        )


def test_eligibility_and_budget_seams_are_independently_implementable() -> None:
    """Fakes satisfy separate seams without token or repository dependencies."""

    eligibility: ContextEligibility = FakeEligibility()
    budgeter: ContextBudgeter = FakeBudgeter()
    inputs = eligibility.get_inputs(uuid4(), ChatMessage(ChatRole.USER, "Question"))

    assert inputs.current_input.content == "Question"
    assert not hasattr(eligibility, "token_counter")
    assert not hasattr(budgeter, "repository")
