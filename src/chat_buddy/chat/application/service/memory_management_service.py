from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from chat_buddy.chat.application.schemas import (
    ManagedMemory,
    MemoryManagementOutcome,
    MemoryManagementResult,
    MemoryProvenance,
    MemorySource,
)
from chat_buddy.chat.domain import (
    ChatMemoryRepository,
    ConversationRepository,
    MemoryDeletionResult,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
    normalize_memory_subject,
    normalize_memory_text,
)


class MemoryManagementService:
    """Coordinate user-initiated inspection and control of Chat memory."""

    def __init__(
        self,
        memory_repository: ChatMemoryRepository,
        conversation_repository: ConversationRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        revision_id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            memory_repository:
                Repository for memory revisions and lifecycle changes.
            conversation_repository:
                Repository used to resolve extracted source information.
            clock:
                Optional timezone-aware clock used for mutations.
            revision_id_factory:
                Optional identifier factory for correction revisions.
        """

        self._memories = memory_repository
        self._conversations = conversation_repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._revision_id_factory = revision_id_factory or uuid4

    def list_memories(
        self, lifecycles: frozenset[MemoryLifecycle] | None = None
    ) -> tuple[ManagedMemory, ...]:
        """List current memories, optionally filtered by lifecycle state.

        Args:
            lifecycles:
                Current lifecycle states to include, or all when omitted.

        Returns:
            Current memory read models in deterministic repository order.
        """

        return tuple(
            self._to_read_model(memory)
            for memory in self._memories.list_memories(lifecycles)
        )

    def inspect_memory(self, memory_id: UUID) -> ManagedMemory | None:
        """Inspect one current memory and its resolved provenance.

        Args:
            memory_id:
                Stable logical-memory identifier.

        Returns:
            Resolved read model, or ``None`` when it no longer exists.
        """

        memory = self._memories.get_memory(memory_id)
        return self._to_read_model(memory) if memory is not None else None

    def correct_memory(
        self,
        memory_id: UUID,
        *,
        expected_revision_id: UUID,
        subject: str,
        content: str,
    ) -> MemoryManagementResult:
        """Correct an active memory with compare-by-revision semantics.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision the user inspected before requesting correction.
            subject:
                Replacement conflict subject.
            content:
                Replacement durable statement.

        Returns:
            Updated, missing, or stale action result.

        Raises:
            ValueError:
                If text is invalid, the target is excluded, or the subject
                conflicts with another current memory.
        """

        current, early_result = self._load_expected(memory_id, expected_revision_id)
        if early_result is not None:
            return early_result
        assert current is not None
        if current.lifecycle is not MemoryLifecycle.ACTIVE:
            raise ValueError(
                "An excluded memory must be reactivated before correction."
            )

        corrected_at = self._now()
        replacement = MemoryRecord(
            id=current.id,
            revision_id=self._revision_id_factory(),
            subject=normalize_memory_subject(subject),
            content=normalize_memory_text(content),
            lifecycle=MemoryLifecycle.ACTIVE,
            origin=MemoryOrigin(
                kind=MemoryOriginKind.USER_CORRECTION,
                superseded_revision_id=current.revision_id,
                corrected_at=corrected_at,
            ),
            created_at=corrected_at,
            updated_at=corrected_at,
        )

        try:
            persisted = self._memories.replace_memory(
                replacement,
                expected_revision_id=expected_revision_id,
            )
        except RuntimeError:
            return MemoryManagementResult(MemoryManagementOutcome.STALE)

        return MemoryManagementResult(
            MemoryManagementOutcome.UPDATED,
            self._to_read_model(persisted),
        )

    def exclude_memory(
        self, memory_id: UUID, *, expected_revision_id: UUID
    ) -> MemoryManagementResult:
        """Exclude a current memory from context eligibility.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision the user inspected before requesting exclusion.

        Returns:
            Updated, unchanged, missing, or stale action result.
        """

        return self._transition(
            memory_id,
            expected_revision_id=expected_revision_id,
            target=MemoryLifecycle.EXCLUDED,
        )

    def reactivate_memory(
        self, memory_id: UUID, *, expected_revision_id: UUID
    ) -> MemoryManagementResult:
        """Restore an excluded memory to context eligibility.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision the user inspected before requesting reactivation.

        Returns:
            Updated, unchanged, missing, or stale action result.
        """

        return self._transition(
            memory_id,
            expected_revision_id=expected_revision_id,
            target=MemoryLifecycle.ACTIVE,
        )

    def delete_memory(
        self, memory_id: UUID, *, expected_revision_id: UUID
    ) -> MemoryManagementResult:
        """Permanently purge a memory lineage if the target is still current.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision the user inspected before requesting deletion.

        Returns:
            Updated, missing, or stale action result.
        """

        result = self._memories.hard_delete(
            memory_id,
            expected_revision_id=expected_revision_id,
        )
        outcomes = {
            MemoryDeletionResult.DELETED: MemoryManagementOutcome.UPDATED,
            MemoryDeletionResult.NOT_FOUND: MemoryManagementOutcome.NOT_FOUND,
            MemoryDeletionResult.STALE: MemoryManagementOutcome.STALE,
        }

        return MemoryManagementResult(outcomes[result])

    def _transition(
        self,
        memory_id: UUID,
        *,
        expected_revision_id: UUID,
        target: MemoryLifecycle,
    ) -> MemoryManagementResult:
        """Apply an idempotent lifecycle transition.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision expected to remain current.
            target:
                Desired current lifecycle.

        Returns:
            Explicit transition result.
        """

        current, early_result = self._load_expected(memory_id, expected_revision_id)
        if early_result is not None:
            return early_result
        assert current is not None
        if current.lifecycle is target:
            return MemoryManagementResult(
                MemoryManagementOutcome.UNCHANGED,
                self._to_read_model(current),
            )

        try:
            transitioned = self._memories.transition_memory(
                memory_id,
                expected_revision_id=expected_revision_id,
                target=target,
                at=self._now(),
            )
        except RuntimeError:
            return MemoryManagementResult(MemoryManagementOutcome.STALE)

        return MemoryManagementResult(
            MemoryManagementOutcome.UPDATED,
            self._to_read_model(transitioned),
        )

    def _load_expected(
        self, memory_id: UUID, expected_revision_id: UUID
    ) -> tuple[MemoryRecord | None, MemoryManagementResult | None]:
        """Load a target and classify missing or stale identities.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision expected to remain current.

        Returns:
            Current record and optional terminal action result.
        """

        current = self._memories.get_memory(memory_id)
        if current is None:
            return None, MemoryManagementResult(MemoryManagementOutcome.NOT_FOUND)
        if current.revision_id != expected_revision_id:
            return None, MemoryManagementResult(MemoryManagementOutcome.STALE)
        return current, None

    def _to_read_model(self, memory: MemoryRecord) -> ManagedMemory:
        """Translate a domain memory and resolve optional source records.

        Args:
            memory:
                Current domain memory record.

        Returns:
            Persistence-neutral application read model.
        """

        origin = memory.origin
        source = self._resolve_source(origin)
        provenance = MemoryProvenance(
            kind=origin.kind,
            source_available=origin.source_available,
            source=source,
            superseded_revision_id=origin.superseded_revision_id,
            corrected_at=origin.corrected_at,
        )
        return ManagedMemory(
            id=memory.id,
            revision_id=memory.revision_id,
            subject=memory.subject,
            content=memory.content,
            lifecycle=memory.lifecycle,
            provenance=provenance,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )

    def _resolve_source(self, origin: MemoryOrigin) -> MemorySource | None:
        """Resolve an available extracted origin through repository contracts.

        Args:
            origin:
                Domain provenance value to resolve.

        Returns:
            Resolved source turn, or ``None`` when unavailable or inconsistent.
        """

        if origin.kind is not MemoryOriginKind.EXTRACTED or not origin.source_available:
            return None

        assert origin.conversation_id is not None
        assert origin.user_message_id is not None
        assert origin.assistant_message_id is not None
        assert origin.generation_attempt_id is not None
        conversation = self._conversations.get_conversation(origin.conversation_id)
        user_message = self._conversations.get_message(origin.user_message_id)
        assistant_message = self._conversations.get_message(origin.assistant_message_id)
        if conversation is None or user_message is None or assistant_message is None:
            return None

        return MemorySource(
            conversation_id=conversation.id,
            conversation_title=conversation.title,
            user_message_id=user_message.id,
            user_message_content=user_message.content,
            assistant_message_id=assistant_message.id,
            assistant_message_content=assistant_message.content,
            generation_attempt_id=origin.generation_attempt_id,
        )

    def _now(self) -> datetime:
        """Return and validate the mutation timestamp.

        Returns:
            Current timezone-aware timestamp.

        Raises:
            ValueError:
                If the configured clock returns a naive timestamp.
        """

        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Memory-management clock must be timezone-aware.")

        return value
