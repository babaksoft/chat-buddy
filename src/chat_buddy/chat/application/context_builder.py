"""Stage 3 context eligibility, summarization, and token budgeting."""

from uuid import UUID

from chat_buddy.chat.application.config import ContextBudgetConfig
from chat_buddy.chat.domain import (
    ChatMemoryRepository,
    ChatMessage,
    ChatRole,
    CompletedTurn,
    ContextAssemblyResult,
    ContextBudgeter,
    ContextEligibility,
    ContextInputs,
    ContextWindowExceededError,
    GenerationConfiguration,
    MemoryRecord,
    ModelDescriptor,
    RollingSummarizer,
    SummaryRepository,
)

_MEMORY_CONTEXT_HEADER = "Relevant memory"
_SUMMARY_CONTEXT_HEADER = "Conversation summary"


class DefaultContextEligibility:
    """Load prompt-eligible Chat data through owning repository contracts."""

    def __init__(
        self,
        memory_repository: ChatMemoryRepository,
        summary_repository: SummaryRepository,
    ) -> None:
        """Initialize eligibility loading.

        Args:
            memory_repository:
                Chat-wide memory persistence contract.
            summary_repository:
                Conversation-scoped summary and completed-turn contract.
        """

        self._memory_repository = memory_repository
        self._summary_repository = summary_repository

    def get_inputs(
        self, conversation_id: UUID, current_input: ChatMessage
    ) -> ContextInputs:
        """Return active memory, local summary, and uncovered complete turns.

        Args:
            conversation_id:
                Conversation whose eligible context should be loaded.
            current_input:
                New or retry user input.

        Returns:
            Deterministically ordered eligible context inputs.
        """

        memories = tuple(
            sorted(
                self._memory_repository.list_eligible_memories(),
                key=lambda memory: (-memory.updated_at.timestamp(), str(memory.id)),
            )
        )
        turns = tuple(
            sorted(
                self._summary_repository.get_uncovered_completed_turns(conversation_id),
                key=lambda turn: (turn.completed_at, str(turn.attempt_id)),
            )
        )

        return ContextInputs(
            conversation_id=conversation_id,
            current_input=current_input,
            memories=memories,
            summary=self._summary_repository.get_active_summary(conversation_id),
            uncovered_turns=turns,
        )


class DefaultContextBudgeter:
    """Select whole eligible items within one model-specific prompt budget."""

    def __init__(self, config: ContextBudgetConfig) -> None:
        """Initialize the budgeter.

        Args:
            config:
                Fixed overhead and mandatory recent-turn policy.
        """

        self._config = config

    def assemble(
        self,
        inputs: ContextInputs,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> ContextAssemblyResult:
        """Apply mandatory priority and greedy whole-item omission.

        Args:
            inputs:
                Eligible context inputs.
            model:
                Selected model and token counter.
            configuration:
                Effective generation settings used for output reservation.

        Returns:
            Formatted context and selection metadata.

        Raises:
            ContextWindowExceededError:
                If prompt capacity is invalid or mandatory content cannot fit.
        """

        capacity = (
            model.context_window_tokens
            - self._config.prompt_overhead_tokens
            - model.output_token_reserve(configuration)
        )
        if capacity <= 0:
            raise ContextWindowExceededError(
                "The selected model leaves no capacity for prompt content."
            )

        minimum_count = min(
            self._config.minimum_recent_turns, len(inputs.uncovered_turns)
        )
        mandatory_turns = inputs.uncovered_turns[-minimum_count:]
        additional_turns = inputs.uncovered_turns[:-minimum_count]
        selected_memories: list[MemoryRecord] = []
        selected_turns = list(mandatory_turns)

        mandatory = self._format(inputs, (), tuple(selected_turns))
        if self._count(mandatory, model) > capacity:
            raise ContextWindowExceededError(
                "Mandatory conversation context exceeds the selected model budget."
            )

        for memory in inputs.memories:
            candidate = self._format(
                inputs, (*selected_memories, memory), tuple(selected_turns)
            )
            if self._count(candidate, model) <= capacity:
                selected_memories.append(memory)

        for turn in reversed(additional_turns):
            candidate_turns = sorted(
                (*selected_turns, turn),
                key=lambda item: (item.completed_at, str(item.attempt_id)),
            )
            candidate = self._format(
                inputs, tuple(selected_memories), tuple(candidate_turns)
            )
            if self._count(candidate, model) <= capacity:
                selected_turns = candidate_turns

        selected_turns.sort(key=lambda item: (item.completed_at, str(item.attempt_id)))
        messages = self._format(inputs, tuple(selected_memories), tuple(selected_turns))
        selected_memory_ids = {memory.id for memory in selected_memories}
        selected_attempt_ids = {turn.attempt_id for turn in selected_turns}

        return ContextAssemblyResult(
            messages=tuple(messages),
            prompt_tokens=self._count(messages, model),
            prompt_capacity=capacity,
            included_memory_ids=tuple(memory.id for memory in selected_memories),
            omitted_memory_ids=tuple(
                memory.id
                for memory in inputs.memories
                if memory.id not in selected_memory_ids
            ),
            included_attempt_ids=tuple(turn.attempt_id for turn in selected_turns),
            omitted_attempt_ids=tuple(
                turn.attempt_id
                for turn in inputs.uncovered_turns
                if turn.attempt_id not in selected_attempt_ids
            ),
        )

    @staticmethod
    def _format(
        inputs: ContextInputs,
        memories: tuple[MemoryRecord, ...],
        turns: tuple[CompletedTurn, ...],
    ) -> list[ChatMessage]:
        """Format selected inputs in provider-facing order.

        Args:
            inputs:
                Boundary inputs containing summary and current input.
            memories:
                Selected whole memory records.
            turns:
                Selected whole complete turns in chronological order.

        Returns:
            Provider-neutral formatted message list.
        """

        messages = [
            ChatMessage(
                ChatRole.SYSTEM,
                f"{_MEMORY_CONTEXT_HEADER}: {memory.subject}\n\n{memory.content}",
            )
            for memory in memories
        ]

        if inputs.summary is not None:
            messages.append(
                ChatMessage(
                    ChatRole.SYSTEM,
                    f"{_SUMMARY_CONTEXT_HEADER}:\n\n{inputs.summary.content}",
                )
            )

        for turn in turns:
            messages.extend(turn.messages)
        messages.append(inputs.current_input)

        return messages

    @staticmethod
    def _count(messages: list[ChatMessage], model: ModelDescriptor) -> int:
        """Count a fully formatted candidate context.

        Args:
            messages:
                Formatted candidate context.
            model:
                Selected model whose counter owns estimation.

        Returns:
            Estimated formatted prompt tokens.
        """

        return model.token_counter.count_tokens(messages)


class ContextAssemblyService:
    """Enforce the shared pre-persistence context assembly boundary."""

    def __init__(
        self,
        eligibility: ContextEligibility,
        budgeter: ContextBudgeter,
        rolling_summarizer: RollingSummarizer,
    ) -> None:
        """Initialize context orchestration.

        Args:
            eligibility:
                Persistence-backed eligible input loader.
            budgeter:
                Persistence-free selected-model budgeter.
            rolling_summarizer:
                Durable conversation summary orchestrator.
        """

        self._eligibility = eligibility
        self._budgeter = budgeter
        self._rolling_summarizer = rolling_summarizer

    def assemble(
        self,
        conversation_id: UUID,
        current_input: ChatMessage,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> ContextAssemblyResult:
        """Validate current input, roll summaries, reload, and budget.

        Args:
            conversation_id:
                Selected conversation identifier.
            current_input:
                New or retry user input.
            model:
                Selected model capabilities.
            configuration:
                Effective response configuration.

        Returns:
            Context proven to fit the selected prompt capacity.
        """

        current_only = ContextInputs(
            conversation_id=conversation_id,
            current_input=current_input,
        )
        self._budgeter.assemble(current_only, model, configuration)
        inputs = self._eligibility.get_inputs(conversation_id, current_input)
        self._rolling_summarizer.update_summary(inputs, model, configuration)
        reloaded = self._eligibility.get_inputs(conversation_id, current_input)
        return self._budgeter.assemble(reloaded, model, configuration)
