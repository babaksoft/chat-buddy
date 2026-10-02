"""Tests for Stage 3 context eligibility and token budgeting."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from chat_buddy.chat.application.config import ContextBudgetConfig
from chat_buddy.chat.application.context_builder import (
    ContextAssemblyService,
    DefaultContextBudgeter,
    DefaultContextEligibility,
)
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextInputs,
    ContextWindowExceededError,
    GenerationConfiguration,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
    ModelDescriptor,
    ModelId,
    ProviderId,
    SummaryLifecycle,
    SummaryProvenance,
    SummaryRecord,
)

_NOW = datetime(2026, 9, 20, tzinfo=UTC)


class CharacterCounter:
    """Count formatted message content characters."""

    def count_tokens(self, messages: list[ChatMessage]) -> int:
        """Return the combined content length.

        Args:
            messages:
                Formatted context.

        Returns:
            Combined content character count.
        """

        return sum(len(message.content) for message in messages)


def _model(window: int, counter: object | None = None) -> ModelDescriptor:
    """Create a deterministic model descriptor.

    Args:
        window:
            Context-window size.
        counter:
            Optional token counter.

    Returns:
        Test model descriptor.
    """

    return ModelDescriptor(
        provider_id=ProviderId("test"),
        id=ModelId(f"model-{window}"),
        display_name="Test model",
        context_window_tokens=window,
        supports_streaming=True,
        supported_generation_parameters=frozenset(),
        default_generation_configuration=GenerationConfiguration(),
        token_counter=counter or CharacterCounter(),  # type: ignore[arg-type]
        default_output_token_reserve=10,
    )


def _turn(conversation_id: UUID, number: int, size: int = 2) -> CompletedTurn:
    """Create one chronological complete turn.

    Args:
        conversation_id:
            Owning conversation.
        number:
            Stable chronological offset.
        size:
            Character count of each message.

    Returns:
        Completed test turn.
    """

    return CompletedTurn(
        conversation_id=conversation_id,
        attempt_id=UUID(int=100 + number),
        user_message_id=UUID(int=200 + number),
        assistant_message_id=UUID(int=300 + number),
        user_content="u" * size,
        assistant_content="a" * size,
        completed_at=_NOW + timedelta(seconds=number),
    )


def _memory(number: int, updated_offset: int = 0) -> MemoryRecord:
    """Create one active Chat-wide memory.

    Args:
        number:
            Stable identifier suffix.
        updated_offset:
            Update-time offset in seconds.

    Returns:
        Active memory record.
    """

    return MemoryRecord(
        id=UUID(int=number),
        revision_id=UUID(int=1000 + number),
        subject=f"subject-{number}",
        content=f"memory-{number}",
        lifecycle=MemoryLifecycle.ACTIVE,
        origin=MemoryOrigin(
            kind=MemoryOriginKind.EXTRACTED,
            source_available=False,
        ),
        created_at=_NOW,
        updated_at=_NOW + timedelta(seconds=updated_offset),
    )


def _summary(conversation_id: UUID) -> SummaryRecord:
    """Create an active local summary.

    Args:
        conversation_id:
            Owning conversation.

    Returns:
        Active summary record.
    """

    return SummaryRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        content="past",
        created_at=_NOW,
        lifecycle=SummaryLifecycle.ACTIVE,
        provenance=SummaryProvenance(
            conversation_id=conversation_id,
            checkpoint_message_id=uuid4(),
        ),
    )


def _budgeter(overhead: int = 0, minimum_turns: int = 2) -> DefaultContextBudgeter:
    """Create a configured context budgeter.

    Args:
        overhead:
            Fixed prompt reserve.
        minimum_turns:
            Mandatory recent complete turns.

    Returns:
        Context budgeter.
    """

    return DefaultContextBudgeter(
        ContextBudgetConfig(
            prompt_overhead_tokens=overhead,
            minimum_recent_turns=minimum_turns,
        )
    )


def test_budget_accepts_exact_fit_after_output_and_overhead_reservation() -> None:
    """An exact prompt-capacity fit is valid and fully accounted."""

    conversation_id = uuid4()
    inputs = ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "12345"),
    )

    result = _budgeter(overhead=5).assemble(
        inputs, _model(20), GenerationConfiguration()
    )

    assert result.prompt_tokens == 5
    assert result.prompt_capacity == 5


def test_budget_uses_smallest_application_provider_and_context_limit() -> None:
    """Cloud-sized windows remain bounded by the application prompt ceiling."""

    base = _model(1_000_000)
    model = ModelDescriptor(
        provider_id=base.provider_id,
        id=base.id,
        display_name=base.display_name,
        context_window_tokens=base.context_window_tokens,
        supports_streaming=base.supports_streaming,
        supported_generation_parameters=base.supported_generation_parameters,
        default_generation_configuration=base.default_generation_configuration,
        token_counter=base.token_counter,
        default_output_token_reserve=10,
        maximum_input_tokens=900_000,
        maximum_output_tokens=100_000,
        application_prompt_limit=65_536,
    )
    inputs = ContextInputs(
        conversation_id=uuid4(),
        current_input=ChatMessage(ChatRole.USER, "hello"),
    )

    result = _budgeter(overhead=64).assemble(inputs, model, GenerationConfiguration())

    assert result.prompt_capacity == 65_472


def test_explicit_output_reservation_can_make_current_input_oversized() -> None:
    """The request output maximum takes precedence over the model default."""

    model = _model(30)
    inputs = ContextInputs(
        conversation_id=uuid4(),
        current_input=ChatMessage(ChatRole.USER, "123456"),
    )

    with pytest.raises(ContextWindowExceededError):
        _budgeter(overhead=5).assemble(
            inputs,
            model,
            GenerationConfiguration(max_output_tokens=20),
        )


def test_budget_keeps_summary_and_recent_turns_before_omitting_memory() -> None:
    """Mandatory local context cannot be displaced by Chat-wide memory."""

    conversation_id = uuid4()
    turn = _turn(conversation_id, 1)
    inputs = ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "q"),
        memories=(_memory(1),),
        summary=_summary(conversation_id),
        uncovered_turns=(turn,),
    )
    mandatory_size = sum(
        len(message.content)
        for message in DefaultContextBudgeter._format(inputs, (), (turn,))
    )

    result = _budgeter(minimum_turns=1).assemble(
        inputs, _model(mandatory_size + 10), GenerationConfiguration()
    )

    assert result.included_attempt_ids == (turn.attempt_id,)
    assert result.omitted_memory_ids == (inputs.memories[0].id,)
    assert result.messages[0].content.startswith("Conversation summary")


def test_optional_turns_are_considered_newest_first_but_rendered_chronologically() -> (
    None
):
    """Whole optional turns follow stable priority and conversational rendering."""

    conversation_id = uuid4()
    turns = tuple(_turn(conversation_id, number) for number in range(3))
    inputs = ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "q"),
        uncovered_turns=turns,
    )
    mandatory = DefaultContextBudgeter._format(inputs, (), (turns[-1],))
    capacity = sum(len(message.content) for message in mandatory) + 4

    result = _budgeter(minimum_turns=1).assemble(
        inputs, _model(capacity + 10), GenerationConfiguration()
    )

    assert result.included_attempt_ids == (turns[1].attempt_id, turns[2].attempt_id)
    assert result.omitted_attempt_ids == (turns[0].attempt_id,)
    assert [message.role for message in result.messages] == [
        ChatRole.USER,
        ChatRole.ASSISTANT,
        ChatRole.USER,
        ChatRole.ASSISTANT,
        ChatRole.USER,
    ]


def test_selected_model_window_and_counter_control_the_result() -> None:
    """Different model capabilities produce independent budget decisions."""

    conversation_id = uuid4()
    memory = _memory(1)
    inputs = ContextInputs(
        conversation_id=conversation_id,
        current_input=ChatMessage(ChatRole.USER, "q"),
        memories=(memory,),
    )
    cheap_counter = Mock()
    cheap_counter.count_tokens.return_value = 1

    included = _budgeter().assemble(
        inputs, _model(20, cheap_counter), GenerationConfiguration()
    )
    omitted = _budgeter().assemble(inputs, _model(20), GenerationConfiguration())

    assert included.included_memory_ids == (memory.id,)
    assert omitted.omitted_memory_ids == (memory.id,)


def test_eligibility_is_chat_wide_for_memory_and_conversation_local_otherwise() -> None:
    """Eligibility orders active memory and asks only for selected local state."""

    conversation_id = uuid4()
    older = _memory(2, updated_offset=1)
    newer = _memory(1, updated_offset=2)
    memories = Mock()
    memories.list_eligible_memories.return_value = (older, newer)
    summaries = Mock()
    summaries.get_active_summary.return_value = None
    summaries.get_uncovered_completed_turns.return_value = (
        _turn(conversation_id, 2),
        _turn(conversation_id, 1),
    )

    inputs = DefaultContextEligibility(memories, summaries).get_inputs(
        conversation_id, ChatMessage(ChatRole.USER, "question")
    )

    assert inputs.memories == (newer, older)
    assert [turn.attempt_id for turn in inputs.uncovered_turns] == [
        UUID(int=101),
        UUID(int=102),
    ]
    summaries.get_active_summary.assert_called_once_with(conversation_id)
    summaries.get_uncovered_completed_turns.assert_called_once_with(conversation_id)


def test_assembly_rejects_oversized_current_input_before_loading_or_summary() -> None:
    """An oversized current input causes no repository or utility work."""

    eligibility = Mock()
    summarizer = Mock()
    service = ContextAssemblyService(eligibility, _budgeter(), summarizer)

    with pytest.raises(ContextWindowExceededError):
        service.assemble(
            uuid4(),
            ChatMessage(ChatRole.USER, "too long"),
            _model(15),
            GenerationConfiguration(),
        )

    eligibility.get_inputs.assert_not_called()
    summarizer.update_summary.assert_not_called()


def test_assembly_reloads_eligibility_after_rolling_summary() -> None:
    """Budgeting consumes authoritative post-summary eligibility."""

    conversation_id = uuid4()
    current = ChatMessage(ChatRole.USER, "q")
    before = ContextInputs(
        conversation_id, current, uncovered_turns=(_turn(conversation_id, 1),)
    )
    after = ContextInputs(conversation_id, current, summary=_summary(conversation_id))
    eligibility = Mock()
    eligibility.get_inputs.side_effect = [before, after]
    summarizer = Mock()
    service = ContextAssemblyService(eligibility, _budgeter(), summarizer)
    model = _model(100)

    result = service.assemble(
        conversation_id, current, model, GenerationConfiguration()
    )

    summarizer.update_summary.assert_called_once_with(
        before, model, GenerationConfiguration()
    )
    assert eligibility.get_inputs.call_count == 2
    assert any(
        message.content.startswith("Conversation summary")
        for message in result.messages
    )
