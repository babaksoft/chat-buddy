from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from chat_buddy.chat.domain.chat import ChatMessage, ChatRole
from chat_buddy.chat.domain.memory import (
    ExtractionReceiptRecord,
    MemoryLifecycle,
    MemoryRecord,
)
from chat_buddy.chat.domain.providers import GenerationConfiguration, ModelDescriptor
from chat_buddy.chat.domain.summary import SummaryLifecycle, SummaryRecord


@dataclass(slots=True, frozen=True)
class CompletedTurn:
    """Persistence-neutral exact user/assistant pair from a completed attempt."""

    conversation_id: UUID
    attempt_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    user_content: str
    assistant_content: str
    completed_at: datetime

    def __post_init__(self) -> None:
        """Validate identifiers, content, and completion time.

        Raises:
            ValueError:
                If the turn is incomplete or malformed.
        """

        identifiers = (
            self.conversation_id,
            self.attempt_id,
            self.user_message_id,
            self.assistant_message_id,
        )
        if any(identifier.int == 0 for identifier in identifiers):
            raise ValueError("Completed-turn identifiers must not be nil UUIDs.")
        if not self.user_content.strip() or not self.assistant_content.strip():
            raise ValueError("A completed turn needs both message contents.")
        if self.completed_at.tzinfo is None:
            raise ValueError("Turn completion time must be timezone-aware.")

    @property
    def messages(self) -> tuple[ChatMessage, ChatMessage]:
        """Return the turn as provider-neutral messages.

        Returns:
            User and assistant messages in conversational order.
        """

        return (
            ChatMessage(ChatRole.USER, self.user_content),
            ChatMessage(ChatRole.ASSISTANT, self.assistant_content),
        )


@dataclass(slots=True, frozen=True)
class ContextInputs:
    """Eligible inputs supplied to token budgeting without persistence access."""

    conversation_id: UUID
    current_input: ChatMessage
    memories: tuple[MemoryRecord, ...] = ()
    summary: SummaryRecord | None = None
    uncovered_turns: tuple[CompletedTurn, ...] = ()

    def __post_init__(self) -> None:
        """Validate ownership, eligibility state, and stable ordering inputs.

        Raises:
            ValueError:
                If an input is ineligible or belongs to another conversation.
        """

        if self.conversation_id.int == 0:
            raise ValueError("Context conversation identifier must not be nil.")

        if self.current_input.role is not ChatRole.USER:
            raise ValueError("Current context input must be a user message.")
        if not self.current_input.content.strip():
            raise ValueError("Current context input must be non-empty.")

        if self.summary is not None:
            if self.summary.conversation_id != self.conversation_id:
                raise ValueError("Context summary belongs to another conversation.")
            if self.summary.lifecycle is not SummaryLifecycle.ACTIVE:
                raise ValueError("Only an active summary is context-eligible.")

        if any(
            turn.conversation_id != self.conversation_id
            for turn in self.uncovered_turns
        ):
            raise ValueError("Context turns must belong to one conversation.")
        if len({turn.attempt_id for turn in self.uncovered_turns}) != len(
            self.uncovered_turns
        ):
            raise ValueError("Uncovered context turns must be unique.")

        if any(
            memory.lifecycle is not MemoryLifecycle.ACTIVE for memory in self.memories
        ):
            raise ValueError("Only active memories are context-eligible.")


@dataclass(slots=True, frozen=True)
class ContextAssemblyResult:
    """Budgeter's persistence-neutral assembled prompt and omission metadata."""

    messages: tuple[ChatMessage, ...]
    prompt_tokens: int
    prompt_capacity: int
    included_memory_ids: tuple[UUID, ...] = ()
    omitted_memory_ids: tuple[UUID, ...] = ()
    included_attempt_ids: tuple[UUID, ...] = ()
    omitted_attempt_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        """Validate budget accounting and unique selection results.

        Raises:
            ValueError:
                If accounting is invalid or an item is both included and omitted.
        """

        if self.prompt_tokens < 0 or self.prompt_capacity <= 0:
            raise ValueError("Context token values must define a positive budget.")
        if self.prompt_tokens > self.prompt_capacity:
            raise ValueError("Assembled context exceeds its prompt capacity.")

        if set(self.included_memory_ids) & set(self.omitted_memory_ids):
            raise ValueError("A memory cannot be both included and omitted.")

        if set(self.included_attempt_ids) & set(self.omitted_attempt_ids):
            raise ValueError("A turn cannot be both included and omitted.")


class ContextEligibility(Protocol):
    """Load context-eligible data without estimating tokens."""

    def get_inputs(
        self, conversation_id: UUID, current_input: ChatMessage
    ) -> ContextInputs:
        """Return eligible inputs for one response boundary.

        Args:
            conversation_id:
                Conversation whose eligible context should be loaded.
            current_input:
                Unpersisted current user input.

        Returns:
            Persistence-neutral eligible inputs without token accounting.
        """

        ...


class ContextBudgeter(Protocol):
    """Assemble supplied eligible inputs without querying persistence."""

    def assemble(
        self,
        inputs: ContextInputs,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> ContextAssemblyResult:
        """Select and format inputs within the selected model budget.

        Args:
            inputs:
                Persistence-neutral eligible context inputs.
            model:
                Selected model capabilities and token counter.
            configuration:
                Effective generation settings used to reserve output capacity.

        Returns:
            Formatted prompt messages and deterministic inclusion metadata.
        """

        ...


class ContextAssembler(Protocol):
    """Prepare one response context through the shared policy."""

    def assemble(
        self,
        conversation_id: UUID,
        current_input: ChatMessage,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> ContextAssemblyResult:
        """Load, summarize, reload, and budget one response context.

        Args:
            conversation_id:
                Selected conversation identifier.
            current_input:
                New or retry user input, supplied exactly once.
            model:
                Selected model capabilities.
            configuration:
                Effective generation settings.

        Returns:
            Validated context within the model prompt capacity.
        """

        ...


class RollingSummarizer(Protocol):
    """Update durable conversation summaries independently of context budgeting."""

    def update_summary(
        self,
        inputs: ContextInputs,
        model: ModelDescriptor,
        configuration: GenerationConfiguration,
    ) -> SummaryRecord | None:
        """Return the active summary after any required rolling update.

        Args:
            inputs:
                Eligible conversation inputs considered for summarization.
            model:
                Selected model whose capacity may trigger an update.
            configuration:
                Effective generation settings used to reserve output capacity.

        Returns:
            Active durable summary, or ``None`` when none exists or is required.
        """

        ...


class MemoryExtractionProcessor(Protocol):
    """Process one exact completed turn independently of response generation."""

    def process(self, turn: CompletedTurn) -> ExtractionReceiptRecord:
        """Process one turn to a durable terminal receipt.

        Args:
            turn:
                Exact completed turn and source provenance to process.

        Returns:
            Succeeded or exhausted bounded-processing receipt.
        """

        ...
