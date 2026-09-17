from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from chat_buddy.chat.domain.chat import ChatRole
from chat_buddy.chat.domain.generation_attempt import GenerationAttemptRecord
from chat_buddy.chat.domain.providers import (
    GenerationConfiguration,
    ModelId,
    ProviderId,
)


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


@dataclass(slots=True, frozen=True)
class MemoryRecord:
    """Persistence-neutral representation of a stored memory."""

    id: int
    key: str
    value: str


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


class MemoryRepository(Protocol):
    """Persistence operations required by memory services."""

    def save_memory(self, key: str, value: str) -> MemoryRecord:
        """Create or update a memory.

        Args:
            key:
                Stable key identifying the memory.
            value:
                Memory value to persist.

        Returns:
            The created or updated memory.
        """

        ...

    def get_memory(self, key: str) -> MemoryRecord | None:
        """Retrieve a memory by key.

        Args:
            key:
                Key of the memory to retrieve.

        Returns:
            The matching memory, or ``None`` when it does not exist.
        """

        ...

    def get_memories(self) -> list[MemoryRecord]:
        """Retrieve all memories in repository order.

        Returns:
            All persisted memories in repository order.
        """

        ...

    def delete_memory(self, key: str) -> bool:
        """Delete a memory when it exists.

        Args:
            key:
                Key of the memory to delete.

        Returns:
            Whether the memory was found and deleted.
        """

        ...
