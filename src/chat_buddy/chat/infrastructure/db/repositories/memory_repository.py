from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast, overload
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from chat_buddy.chat.domain import (
    CompletedTurn,
    ExtractionReceiptRecord,
    GenerationAttemptStatus,
    MemoryCandidate,
    MemoryDeletionResult,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    MemoryRecord,
    normalize_memory_subject,
    normalize_memory_text,
)
from chat_buddy.chat.infrastructure.db.models import (
    ExtractionReceipt,
    GenerationAttempt,
    Memory,
    Message,
)


@dataclass(slots=True, frozen=True)
class StoredMemory:
    """Compatibility result for the provisional key/value application path."""

    id: UUID
    key: str
    value: str


class MemoryRepository:
    """Persists provenance-aware Chat memory revisions and receipts."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository.

        Args:
            session:
                SQLAlchemy session used for repository operations.
        """

        self._session = session

    @overload
    def get_memory(self, memory_id: UUID) -> MemoryRecord | None: ...

    @overload
    def get_memory(self, memory_id: str) -> StoredMemory | None: ...

    def get_memory(self, memory_id: UUID | str) -> MemoryRecord | StoredMemory | None:
        """Return a logical memory or a provisional subject-key lookup.

        Args:
            memory_id:
                Logical UUID, or a provisional normalized subject key.

        Returns:
            Current domain record or compatibility result when found.
        """

        if isinstance(memory_id, str):
            model = self._current_by_subject(normalize_memory_subject(memory_id))
            return self._to_stored(model) if model is not None else None
        model = self._current_by_memory_id(memory_id)
        return self._to_record(model) if model is not None else None

    def get_revision(self, revision_id: UUID) -> MemoryRecord | None:
        """Return one specific memory revision.

        Args:
            revision_id:
                Stable revision identifier.

        Returns:
            Matching record, or ``None``.
        """

        model = self._session.get(Memory, revision_id)
        return self._to_record(model) if model is not None else None

    def list_memories(
        self, lifecycles: frozenset[MemoryLifecycle] | None = None
    ) -> tuple[MemoryRecord, ...]:
        """Return current memory revisions in deterministic order.

        Args:
            lifecycles:
                Optional current lifecycle states to include.

        Returns:
            Current revisions ordered by creation time and identifier.
        """

        statement = select(Memory).where(Memory.lifecycle != MemoryLifecycle.SUPERSEDED)
        if lifecycles is not None:
            statement = statement.where(Memory.lifecycle.in_(lifecycles))
        statement = statement.order_by(Memory.created_at, Memory.revision_id)
        return tuple(self._to_record(item) for item in self._session.scalars(statement))

    def list_eligible_memories(self) -> tuple[MemoryRecord, ...]:
        """Return active current revisions in deterministic prompt order.

        Returns:
            Chat-wide eligible memory records.
        """

        return self.list_memories(frozenset({MemoryLifecycle.ACTIVE}))

    def find_current_by_subject(self, subject: str) -> MemoryRecord | None:
        """Return the current revision for a normalized subject.

        Args:
            subject:
                Normalized subject used for conflict detection.

        Returns:
            Current matching record, or ``None``.
        """

        normalized = normalize_memory_subject(subject)
        if normalized != subject:
            raise ValueError("Memory subject must already be normalized.")
        model = self._current_by_subject(normalized)
        return self._to_record(model) if model is not None else None

    def replace_memory(
        self,
        replacement: MemoryRecord,
        *,
        expected_revision_id: UUID,
    ) -> MemoryRecord:
        """Atomically persist a correction and supersede its prior revision.

        Args:
            replacement:
                Validated replacement record.
            expected_revision_id:
                Revision expected to be current.

        Returns:
            Persisted replacement.

        Raises:
            ValueError:
                If correction provenance, state, or subject conflicts.
            RuntimeError:
                If the expected revision is stale.
        """

        current = self._lock_current(replacement.id)
        if current is None or current.revision_id != expected_revision_id:
            raise RuntimeError(
                "The current memory revision changed before replacement."
            )
        current_record = self._to_record(current)
        if current_record.lifecycle is not MemoryLifecycle.ACTIVE:
            raise ValueError("Only an active memory can be corrected.")
        if replacement.lifecycle is not MemoryLifecycle.ACTIVE:
            raise ValueError("A replacement memory must be active.")
        if replacement.origin.kind is not MemoryOriginKind.USER_CORRECTION:
            raise ValueError("A user replacement needs correction provenance.")
        if replacement.origin.superseded_revision_id != expected_revision_id:
            raise ValueError("Correction provenance must identify the prior revision.")
        if replacement.id != current.memory_id:
            raise ValueError("A replacement must remain in the same memory lineage.")

        subject_owner = self._current_by_subject(replacement.subject, lock=True)
        if subject_owner is not None and subject_owner.memory_id != replacement.id:
            raise ValueError("Another current memory already uses this subject.")

        current.lifecycle = MemoryLifecycle.SUPERSEDED
        current.updated_at = replacement.updated_at
        try:
            self._session.add(self._from_record(replacement))
            self._session.commit()
            return replacement
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def transition_memory(
        self,
        memory_id: UUID,
        *,
        expected_revision_id: UUID,
        target: MemoryLifecycle,
        at: datetime,
    ) -> MemoryRecord:
        """Atomically transition a current revision with stale-write detection.

        Args:
            memory_id:
                Stable logical-memory identifier.
            expected_revision_id:
                Revision expected to be current.
            target:
                Requested lifecycle state.
            at:
                Time of the transition.

        Returns:
            Updated memory record.

        Raises:
            RuntimeError:
                If the expected current revision is stale.
        """

        model = self._lock_current(memory_id)
        if model is None or model.revision_id != expected_revision_id:
            raise RuntimeError("The current memory revision changed before transition.")
        transitioned = self._to_record(model).transition(target, at=at)
        model.lifecycle = transitioned.lifecycle
        model.updated_at = transitioned.updated_at
        try:
            self._session.commit()
            return transitioned
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def process_extraction(
        self,
        turn: CompletedTurn,
        candidates: tuple[MemoryCandidate, ...],
        receipt: ExtractionReceiptRecord,
    ) -> ExtractionReceiptRecord:
        """Atomically apply extracted candidates and terminal receipt.

        Args:
            turn:
                Exact completed turn supplying provenance.
            candidates:
                Complete normalized candidate set.
            receipt:
                Terminal attempt-level processing receipt.

        Returns:
            Persisted receipt, or the pre-existing terminal receipt.

        Raises:
            ValueError:
                If turn, receipt, or candidate data is inconsistent.
        """

        try:
            existing = self.get_extraction_receipt(turn.attempt_id)
            if existing is not None:
                return existing
            if receipt.generation_attempt_id != turn.attempt_id:
                raise ValueError("Extraction receipt must identify the completed turn.")
            if receipt.outcome.value == "exhausted" and candidates:
                raise ValueError("An exhausted extraction cannot persist candidates.")
            self._validate_completed_turn(turn)

            for candidate in candidates:
                current = self._current_by_subject(candidate.subject, lock=True)
                if current is not None:
                    record = self._to_record(current)
                    if record.lifecycle is MemoryLifecycle.EXCLUDED:
                        continue
                    if record.origin.kind is MemoryOriginKind.USER_CORRECTION:
                        continue
                    if record.content == candidate.content:
                        continue
                    current.lifecycle = MemoryLifecycle.SUPERSEDED
                    current.updated_at = receipt.completed_at
                    memory_id = current.memory_id
                else:
                    memory_id = uuid4()

                self._session.add(
                    self._extracted_model(
                        memory_id=memory_id,
                        candidate=candidate,
                        turn=turn,
                        at=receipt.completed_at,
                    )
                )

            self._session.add(
                ExtractionReceipt(
                    generation_attempt_id=receipt.generation_attempt_id,
                    generation_attempt_status=GenerationAttemptStatus.COMPLETED,
                    outcome=receipt.outcome,
                    attempt_count=receipt.attempt_count,
                    completed_at=receipt.completed_at,
                )
            )
            self._session.commit()
            return receipt
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def get_extraction_receipt(
        self, generation_attempt_id: UUID
    ) -> ExtractionReceiptRecord | None:
        """Return a completed attempt's terminal extraction receipt.

        Args:
            generation_attempt_id:
                Completed generation attempt identifier.

        Returns:
            Matching terminal receipt, or ``None``.
        """

        model = self._session.get(ExtractionReceipt, generation_attempt_id)
        if model is None:
            return None
        return ExtractionReceiptRecord(
            generation_attempt_id=model.generation_attempt_id,
            outcome=model.outcome,
            attempt_count=model.attempt_count,
            completed_at=self._aware(model.completed_at),
        )

    def mark_source_unavailable(self, conversation_id: UUID) -> int:
        """Clear extracted provenance before deleting a source conversation.

        Args:
            conversation_id:
                Source conversation being deleted.

        Returns:
            Number of affected memory revisions.
        """

        statement = (
            update(Memory)
            .where(
                Memory.origin_kind == MemoryOriginKind.EXTRACTED,
                Memory.source_conversation_id == conversation_id,
            )
            .values(
                source_available=False,
                source_conversation_id=None,
                source_user_message_id=None,
                source_assistant_message_id=None,
                source_generation_attempt_id=None,
                source_generation_status=None,
            )
        )
        try:
            result = cast(CursorResult[Any], self._session.execute(statement))
            self._session.commit()
            return result.rowcount
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def get_origin(self, revision_id: UUID) -> MemoryOrigin | None:
        """Return provenance for one memory revision.

        Args:
            revision_id:
                Stable revision identifier.

        Returns:
            Matching origin value, or ``None``.
        """

        model = self._session.get(Memory, revision_id)
        return self._origin(model) if model is not None else None

    def hard_delete(self, memory_id: UUID) -> MemoryDeletionResult:
        """Permanently delete a logical memory and its entire lineage.

        Args:
            memory_id:
                Stable logical-memory identifier.

        Returns:
            Whether a logical memory was deleted.
        """

        if self._current_by_memory_id(memory_id) is None:
            return MemoryDeletionResult.NOT_FOUND
        try:
            self._session.execute(delete(Memory).where(Memory.memory_id == memory_id))
            self._session.commit()
            return MemoryDeletionResult.DELETED
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def save_memory(self, key: str, value: str) -> StoredMemory:
        """Persist through the provisional key/value compatibility path.

        Args:
            key:
                Prototype memory key, treated as a normalized subject.
            value:
                Prototype memory value, treated as normalized content.

        Returns:
            Stored compatibility result.
        """

        subject = normalize_memory_subject(key)
        content = normalize_memory_text(value)
        current = self._current_by_subject(subject)
        at = datetime.now(UTC)
        if current is None:
            model = Memory(
                revision_id=uuid4(),
                memory_id=uuid4(),
                subject=subject,
                content=content,
                lifecycle=MemoryLifecycle.ACTIVE,
                origin_kind=MemoryOriginKind.EXTRACTED,
                source_available=False,
                created_at=at,
                updated_at=at,
            )
        else:
            current.content = content
            current.updated_at = at
            model = current
        try:
            self._session.add(model)
            self._session.commit()
            return self._to_stored(model)
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def get_memories(self) -> list[StoredMemory]:
        """Return current memories through the compatibility shape.

        Returns:
            Current memories ordered by subject.
        """

        statement = (
            select(Memory)
            .where(Memory.lifecycle != MemoryLifecycle.SUPERSEDED)
            .order_by(Memory.subject)
        )
        return [self._to_stored(item) for item in self._session.scalars(statement)]

    def delete_memory(self, key: str) -> bool:
        """Delete one compatibility memory by normalized subject.

        Args:
            key:
                Prototype subject key.

        Returns:
            Whether a matching logical memory was deleted.
        """

        current = self._current_by_subject(normalize_memory_subject(key))
        if current is None:
            return False
        return self.hard_delete(current.memory_id) is MemoryDeletionResult.DELETED

    def _validate_completed_turn(self, turn: CompletedTurn) -> None:
        """Verify exact turn provenance against committed persistence.

        Args:
            turn:
                Completed turn to validate.

        Raises:
            ValueError:
                If persisted provenance or content differs.
        """

        attempt = self._session.get(GenerationAttempt, turn.attempt_id)
        user = self._session.get(Message, turn.user_message_id)
        assistant = self._session.get(Message, turn.assistant_message_id)
        if (
            attempt is None
            or user is None
            or assistant is None
            or attempt.status is not GenerationAttemptStatus.COMPLETED
            or attempt.conversation_id != turn.conversation_id
            or attempt.source_user_message_id != turn.user_message_id
            or attempt.assistant_message_id != turn.assistant_message_id
            or attempt.submitted_user_content != turn.user_content
            or assistant.content != turn.assistant_content
        ):
            raise ValueError("Extraction turn does not match a completed attempt.")

    def _current_by_memory_id(self, memory_id: UUID) -> Memory | None:
        """Load the current entity for a logical memory.

        Args:
            memory_id:
                Stable logical-memory identifier.

        Returns:
            Current persistence entity, or ``None``.
        """

        statement = select(Memory).where(
            Memory.memory_id == memory_id,
            Memory.lifecycle != MemoryLifecycle.SUPERSEDED,
        )
        return self._session.scalar(statement)

    def _lock_current(self, memory_id: UUID) -> Memory | None:
        """Load and lock the current entity for a logical memory.

        Args:
            memory_id:
                Stable logical-memory identifier.

        Returns:
            Locked current entity, or ``None``.
        """

        statement = (
            select(Memory)
            .where(
                Memory.memory_id == memory_id,
                Memory.lifecycle != MemoryLifecycle.SUPERSEDED,
            )
            .with_for_update()
        )
        return self._session.scalar(statement)

    def _current_by_subject(self, subject: str, *, lock: bool = False) -> Memory | None:
        """Load the current entity for a normalized subject.

        Args:
            subject:
                Normalized memory subject.
            lock:
                Whether to acquire a row lock.

        Returns:
            Current persistence entity, or ``None``.
        """

        statement = select(Memory).where(
            Memory.subject == subject,
            Memory.lifecycle != MemoryLifecycle.SUPERSEDED,
        )
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    @staticmethod
    def _extracted_model(
        *,
        memory_id: UUID,
        candidate: MemoryCandidate,
        turn: CompletedTurn,
        at: datetime,
    ) -> Memory:
        """Create an extracted persistence entity.

        Args:
            memory_id:
                Stable logical-memory identifier.
            candidate:
                Normalized candidate to persist.
            turn:
                Exact completed source turn.
            at:
                Revision creation time.

        Returns:
            New unpersisted memory entity.
        """

        return Memory(
            revision_id=uuid4(),
            memory_id=memory_id,
            subject=candidate.subject,
            content=candidate.content,
            lifecycle=MemoryLifecycle.ACTIVE,
            origin_kind=MemoryOriginKind.EXTRACTED,
            source_available=True,
            source_conversation_id=turn.conversation_id,
            source_user_message_id=turn.user_message_id,
            source_assistant_message_id=turn.assistant_message_id,
            source_generation_attempt_id=turn.attempt_id,
            source_generation_status=GenerationAttemptStatus.COMPLETED,
            created_at=at,
            updated_at=at,
        )

    @staticmethod
    def _from_record(record: MemoryRecord) -> Memory:
        """Translate a domain record into a persistence entity.

        Args:
            record:
                Immutable memory record.

        Returns:
            New unpersisted memory entity.
        """

        origin = record.origin
        return Memory(
            revision_id=record.revision_id,
            memory_id=record.id,
            subject=record.subject,
            content=record.content,
            lifecycle=record.lifecycle,
            origin_kind=origin.kind,
            source_available=origin.source_available,
            source_conversation_id=origin.conversation_id,
            source_user_message_id=origin.user_message_id,
            source_assistant_message_id=origin.assistant_message_id,
            source_generation_attempt_id=origin.generation_attempt_id,
            source_generation_status=(
                GenerationAttemptStatus.COMPLETED
                if origin.kind is MemoryOriginKind.EXTRACTED and origin.source_available
                else None
            ),
            superseded_revision_id=origin.superseded_revision_id,
            corrected_at=origin.corrected_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_record(model: Memory) -> MemoryRecord:
        """Translate a persistence entity into a domain record.

        Args:
            model:
                Persisted memory entity.

        Returns:
            Immutable memory record.
        """

        return MemoryRecord(
            id=model.memory_id,
            revision_id=model.revision_id,
            subject=model.subject,
            content=model.content,
            lifecycle=model.lifecycle,
            origin=MemoryRepository._origin(model),
            created_at=MemoryRepository._aware(model.created_at),
            updated_at=MemoryRepository._aware(model.updated_at),
        )

    @staticmethod
    def _origin(model: Memory) -> MemoryOrigin:
        """Translate persisted provenance into a domain value.

        Args:
            model:
                Persisted memory entity.

        Returns:
            Immutable memory origin.
        """

        return MemoryOrigin(
            kind=model.origin_kind,
            source_available=model.source_available,
            conversation_id=model.source_conversation_id,
            user_message_id=model.source_user_message_id,
            assistant_message_id=model.source_assistant_message_id,
            generation_attempt_id=model.source_generation_attempt_id,
            superseded_revision_id=model.superseded_revision_id,
            corrected_at=(
                MemoryRepository._aware(model.corrected_at)
                if model.corrected_at is not None
                else None
            ),
        )

    @staticmethod
    def _to_stored(model: Memory) -> StoredMemory:
        """Translate an entity into the provisional compatibility shape.

        Args:
            model:
                Persisted memory entity.

        Returns:
            Compatibility memory result.
        """

        return StoredMemory(id=model.memory_id, key=model.subject, value=model.content)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        """Normalize a SQLite-naive timestamp to UTC.

        Args:
            value:
                Persisted timestamp.

        Returns:
            Timezone-aware timestamp.
        """

        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
