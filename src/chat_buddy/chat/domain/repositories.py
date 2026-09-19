from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from chat_buddy.chat.domain.chat import ChatRole
from chat_buddy.chat.domain.context import CompletedTurn
from chat_buddy.chat.domain.generation_attempt import GenerationAttemptRecord
from chat_buddy.chat.domain.memory import (
    ChatMemory,
    MemoryCandidate,
    MemoryDeletionResult,
    MemoryExtractionReceipt,
    MemoryLifecycle,
    MemoryOrigin,
)
from chat_buddy.chat.domain.providers import (
    GenerationConfiguration,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.domain.summary import ConversationSummary


@dataclass(slots=True, frozen=True)
class ConversationRecord:
    """Persistence-neutral conversation and its requested generation defaults."""

    id: UUID
    title: str | None
    provider_id: ProviderId | None = None
    model_id: ModelId | None = None
    requested_generation_configuration: GenerationConfiguration = field(
        default_factory=GenerationConfiguration
    )


@dataclass(slots=True, frozen=True)
class MessageRecord:
    """Persistence-neutral representation of a conversation message."""

    id: UUID
    conversation_id: UUID
    role: ChatRole
    content: str


class ConversationRepository(Protocol):
    """Persistence operations required by conversation and generation services."""

    def create_conversation(
        self,
        title: str | None = None,
        provider_id: ProviderId | None = None,
        model_id: ModelId | None = None,
        requested_generation_configuration: GenerationConfiguration | None = None,
    ) -> ConversationRecord:
        """Create and persist a conversation.

        Args:
            title:
                Optional conversation title.
            provider_id:
                Optional selected response provider.
            model_id:
                Optional selected provider-local model.
            requested_generation_configuration:
                Optional provider-neutral defaults requested for future attempts.

        Returns:
            The persisted conversation.
        """

        ...

    def update_generation_defaults(
        self,
        conversation_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        requested_configuration: GenerationConfiguration,
    ) -> ConversationRecord | None:
        """Persist defaults to use for a conversation's next attempt.

        Args:
            conversation_id:
                Identifier of the conversation to update.
            provider_id:
                Selected response provider.
            model_id:
                Selected provider-local model.
            requested_configuration:
                Provider-neutral requested generation values.

        Returns:
            The updated conversation, or ``None`` when it does not exist.
        """

        ...

    def get_conversation(
        self,
        conversation_id: UUID,
    ) -> ConversationRecord | None:
        """Retrieve a conversation by identifier.

        Args:
            conversation_id:
                Identifier of the conversation to retrieve.

        Returns:
            The matching conversation, or ``None`` when it does not exist.
        """

        ...

    def get_conversations(self) -> list[ConversationRecord]:
        """Retrieve all conversations in repository order.

        Returns:
            All persisted conversations in repository order.
        """

        ...

    def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
    ) -> bool:
        """Rename a conversation when it exists.

        Args:
            conversation_id:
                Identifier of the conversation to rename.
            title:
                New conversation title.

        Returns:
            Whether the conversation was found and renamed.
        """

        ...

    def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation when it exists.

        Args:
            conversation_id:
                Identifier of the conversation to delete.

        Returns:
            Whether the conversation was found and deleted.
        """

        ...

    def add_message(
        self,
        conversation_id: UUID,
        role: ChatRole,
        content: str,
    ) -> MessageRecord:
        """Persist a message in a conversation.

        Args:
            conversation_id:
                Identifier of the conversation receiving the message.
            role:
                Role of the message author.
            content:
                Message text to persist.

        Returns:
            The persisted message.
        """

        ...

    def get_messages(self, conversation_id: UUID) -> list[MessageRecord]:
        """Retrieve a conversation's messages in repository order.

        Args:
            conversation_id:
                Identifier of the conversation whose messages to retrieve.

        Returns:
            The conversation's messages in repository order.
        """

        ...

    def get_message(self, message_id: UUID) -> MessageRecord | None:
        """Retrieve one message by identifier.

        Args:
            message_id:
                Identifier of the message to retrieve.

        Returns:
            The matching message, or ``None`` when it does not exist.
        """

        ...

    def get_unmatched_user_message(self, conversation_id: UUID) -> MessageRecord | None:
        """Return the singular unanswered final user message, when present.

        Args:
            conversation_id:
                Conversation whose linear tail should be inspected.

        Returns:
            Unmatched final user message, or ``None`` for a closed turn.
        """

        ...

    def edit_unmatched_user_message(
        self, conversation_id: UUID, content: str
    ) -> MessageRecord:
        """Edit the unmatched tail while no generation attempt is open.

        Args:
            conversation_id:
                Conversation containing the editable tail.
            content:
                Replacement user content.

        Returns:
            Updated unmatched user message.

        Raises:
            LookupError:
                If the conversation has no unmatched user-message tail.
            InvalidGenerationAttemptTransitionError:
                If an attempt is currently open.
        """

        ...

    def start_generation_attempt(
        self,
        conversation_id: UUID,
        user_content: str,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Atomically persist a user message and its pending attempt.

        Args:
            conversation_id:
                Identifier of the target conversation.
            user_content:
                Source user-message content.
            provider_id:
                Effective response provider.
            model_id:
                Effective provider-local model.
            effective_configuration:
                Validated immutable generation settings.

        Returns:
            The newly persisted pending attempt.

        Raises:
            LookupError:
                If the target conversation does not exist.
        """

        ...

    def retry_generation_attempt(
        self,
        attempt_id: UUID,
        provider_id: ProviderId,
        model_id: ModelId,
        effective_configuration: GenerationConfiguration,
    ) -> GenerationAttemptRecord:
        """Create a pending retry that reuses an incomplete attempt's source.

        Args:
            attempt_id:
                Identifier of the failed or interrupted attempt to retry.
            provider_id:
                Effective response provider for the new attempt.
            model_id:
                Effective provider-local model for the new attempt.
            effective_configuration:
                Validated immutable generation settings for the new attempt.

        Returns:
            The newly persisted pending retry attempt.

        Raises:
            LookupError:
                If the source attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the source attempt is not failed or interrupted.
        """

        ...

    def begin_generation_attempt(
        self, attempt_id: UUID, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Transition a pending attempt to streaming.

        Args:
            attempt_id:
                Identifier of the attempt to start.
            at:
                Time response streaming started.

        Returns:
            The updated streaming attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not pending or the timestamp is invalid.
        """

        ...

    def checkpoint_generation_attempt(
        self, attempt_id: UUID, partial_content: str
    ) -> GenerationAttemptRecord:
        """Replace the partial content of a streaming attempt.

        Args:
            attempt_id:
                Identifier of the attempt to checkpoint.
            partial_content:
                Complete output accumulated so far.

        Returns:
            The updated streaming attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming.
        """

        ...

    def complete_generation_attempt(
        self, attempt_id: UUID, assistant_content: str, *, at: datetime
    ) -> GenerationAttemptRecord:
        """Atomically persist an assistant message and complete its attempt.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            assistant_content:
                Completed assistant response.
            at:
                Time generation completed.

        Returns:
            The completed attempt linked to its assistant message.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or the timestamp is invalid.
        """

        ...

    def fail_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        error_code: str,
        at: datetime,
        error_detail: str | None = None,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Mark a streaming attempt failed with safe diagnostics.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            error_code:
                Stable normalized failure code.
            at:
                Time of generation attempt failure.
            error_detail:
                Optional safe user-facing detail.
            partial_content:
                Optional complete partial output.

        Returns:
            The failed attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or failure data is invalid.
        """

        ...

    def interrupt_generation_attempt(
        self,
        attempt_id: UUID,
        *,
        at: datetime,
        partial_content: str | None = None,
    ) -> GenerationAttemptRecord:
        """Mark a streaming attempt interrupted.

        Args:
            attempt_id:
                Identifier of the streaming attempt.
            at:
                Time generation was interrupted.
            partial_content:
                Optional complete partial output.

        Returns:
            The interrupted attempt.

        Raises:
            LookupError:
                If the attempt does not exist.
            InvalidGenerationAttemptTransitionError:
                If the attempt is not streaming or the timestamp is invalid.
        """

        ...

    def get_generation_attempt(
        self, attempt_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Retrieve a generation attempt by identifier.

        Args:
            attempt_id:
                Identifier of the attempt to retrieve.

        Returns:
            The matching attempt, or ``None`` when it does not exist.
        """

        ...

    def get_open_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the singular pending or streaming attempt, when present.

        Args:
            conversation_id:
                Identifier of the conversation to inspect.

        Returns:
            Open attempt, or ``None`` when no invocation is active.

        Raises:
            RuntimeError:
                If provisional persistence contains multiple open attempts.
        """

        ...

    def get_latest_retryable_generation_attempt(
        self, conversation_id: UUID
    ) -> GenerationAttemptRecord | None:
        """Return the latest retry target for the unmatched tail, when present.

        Args:
            conversation_id:
                Conversation whose linear tail should be inspected.

        Returns:
            Latest failed or interrupted attempt for the unmatched final user
            message, or ``None`` when the tail is closed or an attempt is open.
        """

        ...

    def get_generation_attempts(
        self, conversation_id: UUID
    ) -> list[GenerationAttemptRecord]:
        """Retrieve all attempts for a conversation.

        Args:
            conversation_id:
                Identifier of the conversation to inspect.

        Returns:
            Attempts ordered from oldest to newest.
        """

        ...


class SummaryRepository(Protocol):
    """Persistence contract for conversation-owned summary versions."""

    def get_active_summary(self, conversation_id: UUID) -> ConversationSummary | None:
        """Return the active summary for a conversation, when present.

        Args:
            conversation_id:
                Conversation whose active summary should be retrieved.

        Returns:
            Active summary version, or ``None`` when the conversation has none.
        """

        ...

    def get_summary(self, summary_id: UUID) -> ConversationSummary | None:
        """Return one summary version by stable identifier.

        Args:
            summary_id:
                Stable summary-version identifier.

        Returns:
            Matching summary version, or ``None`` when it does not exist.
        """

        ...

    def replace_active_summary(
        self,
        summary: ConversationSummary,
        *,
        expected_active_id: UUID | None,
    ) -> ConversationSummary:
        """Atomically activate a version and supersede its predecessor.

        Args:
            summary:
                New active summary version to persist.
            expected_active_id:
                Identifier of the version expected to be active, or ``None``
                when creating the first version.

        Returns:
            Persisted active summary version.

        Raises:
            ValueError:
                If ownership, provenance, or lifecycle values are invalid.
            RuntimeError:
                If the expected active version is stale.
        """

        ...

    def get_uncovered_completed_turns(
        self, conversation_id: UUID
    ) -> tuple[CompletedTurn, ...]:
        """Return complete turns absent from the active summary lineage.

        Args:
            conversation_id:
                Conversation whose summary coverage should be inspected.

        Returns:
            Uncovered complete turns in deterministic chronological order.
        """

        ...


class ChatMemoryRepository(Protocol):
    """Persistence contract for provenance-aware logical Chat memories."""

    def get_memory(self, memory_id: UUID) -> ChatMemory | None:
        """Return the current revision of one logical memory.

        Args:
            memory_id:
                Stable logical-memory identifier.

        Returns:
            Current revision, or ``None`` when the memory does not exist.
        """

        ...

    def get_revision(self, revision_id: UUID) -> ChatMemory | None:
        """Return a specific memory revision including its provenance.

        Args:
            revision_id:
                Stable revision identifier.

        Returns:
            Matching revision, or ``None`` when it does not exist.
        """

        ...

    def list_memories(
        self, lifecycles: frozenset[MemoryLifecycle] | None = None
    ) -> tuple[ChatMemory, ...]:
        """Return current memories, optionally filtered by lifecycle.

        Args:
            lifecycles:
                Lifecycle states to include, or ``None`` to include all states.

        Returns:
            Current logical-memory revisions in deterministic order.
        """

        ...

    def list_eligible_memories(self) -> tuple[ChatMemory, ...]:
        """Return active current revisions in deterministic context order.

        Returns:
            Chat-wide prompt-eligible memory revisions.
        """

        ...

    def find_current_by_subject(self, subject: str) -> ChatMemory | None:
        """Return the current logical memory with a normalized subject.

        Args:
            subject:
                Normalized subject used for conflict detection.

        Returns:
            Matching current revision, or ``None`` when no subject matches.
        """

        ...

    def replace_memory(
        self,
        replacement: ChatMemory,
        *,
        expected_revision_id: UUID,
    ) -> ChatMemory:
        """Atomically add a replacement and supersede the expected revision.

        Args:
            replacement:
                New current revision to persist.
            expected_revision_id:
                Current revision expected before replacement.

        Returns:
            Persisted replacement revision.

        Raises:
            ValueError:
                If the replacement is invalid or conflicts with another lineage.
            RuntimeError:
                If the expected current revision is stale.
        """

        ...

    def transition_memory(
        self,
        memory_id: UUID,
        *,
        expected_revision_id: UUID,
        target: MemoryLifecycle,
        at: datetime,
    ) -> ChatMemory:
        """Atomically apply a legal lifecycle transition to a current revision.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Current revision expected before the transition.
            target:
                Requested target lifecycle state.
            at:
                Time at which the transition occurs.

        Returns:
            Updated current memory revision.

        Raises:
            ValueError:
                If the lifecycle transition or timestamp is invalid.
            RuntimeError:
                If the expected current revision is stale.
        """

        ...

    def process_extraction(
        self,
        turn: CompletedTurn,
        candidates: tuple[MemoryCandidate, ...],
        receipt: MemoryExtractionReceipt,
    ) -> MemoryExtractionReceipt:
        """Atomically apply candidates and store one terminal receipt.

        Args:
            turn:
                Exact completed turn and its source provenance.
            candidates:
                Normalized candidates produced from the turn.
            receipt:
                Terminal processing receipt for the completed attempt.

        Returns:
            Persisted terminal receipt.

        Raises:
            ValueError:
                If the turn or a candidate is inconsistent with persistence.
        """

        ...

    def get_extraction_receipt(
        self, generation_attempt_id: UUID
    ) -> MemoryExtractionReceipt | None:
        """Return an attempt's terminal extraction receipt, when present.

        Args:
            generation_attempt_id:
                Completed generation-attempt identifier.

        Returns:
            Succeeded or exhausted receipt, or ``None`` when unprocessed.
        """

        ...

    def mark_source_unavailable(self, conversation_id: UUID) -> int:
        """Clear source references owned by a deleted conversation.

        Args:
            conversation_id:
                Deleted source-conversation identifier.

        Returns:
            Number of extracted origins marked unavailable.
        """

        ...

    def get_origin(self, revision_id: UUID) -> MemoryOrigin | None:
        """Return the provenance of a memory revision.

        Args:
            revision_id:
                Stable revision identifier.

        Returns:
            Matching origin, or ``None`` when the revision does not exist.
        """

        ...

    def hard_delete(self, memory_id: UUID) -> MemoryDeletionResult:
        """Purge a logical memory, revisions, observations, and provenance.

        Args:
            memory_id:
                Stable logical-memory identifier to purge.

        Returns:
            Terminal deletion outcome without retaining a tombstone.
        """

        ...
