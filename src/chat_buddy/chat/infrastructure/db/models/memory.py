from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKeyConstraint, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chat_buddy.chat.domain import (
    GenerationAttemptStatus,
    MemoryExtractionOutcome,
    MemoryLifecycle,
    MemoryOriginKind,
)
from chat_buddy.chat.infrastructure.db.base import CHAT_SCHEMA, ChatBase

if TYPE_CHECKING:
    from chat_buddy.chat.infrastructure.db.models.generation_attempt import (
        GenerationAttempt,
    )


class Memory(ChatBase):
    """Represents one persisted revision in a logical Chat memory lineage."""

    __tablename__ = "memories"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "source_generation_attempt_id",
                "source_conversation_id",
                "source_user_message_id",
                "source_assistant_message_id",
                "source_generation_status",
            ],
            [
                f"{CHAT_SCHEMA}.generation_attempts.id",
                f"{CHAT_SCHEMA}.generation_attempts.conversation_id",
                f"{CHAT_SCHEMA}.generation_attempts.source_user_message_id",
                f"{CHAT_SCHEMA}.generation_attempts.assistant_message_id",
                f"{CHAT_SCHEMA}.generation_attempts.status",
            ],
            name="fk_memory_completed_source",
        ),
        ForeignKeyConstraint(
            ["superseded_revision_id"],
            [f"{CHAT_SCHEMA}.memories.revision_id"],
            name="fk_memory_corrected_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(origin_kind = 'extracted' AND superseded_revision_id IS NULL "
            "AND corrected_at IS NULL AND ((source_available = true "
            "AND source_conversation_id IS NOT NULL "
            "AND source_user_message_id IS NOT NULL "
            "AND source_assistant_message_id IS NOT NULL "
            "AND source_generation_attempt_id IS NOT NULL "
            "AND source_generation_status = 'completed') OR "
            "(source_available = false AND source_conversation_id IS NULL "
            "AND source_user_message_id IS NULL "
            "AND source_assistant_message_id IS NULL "
            "AND source_generation_attempt_id IS NULL "
            "AND source_generation_status IS NULL))) OR "
            "(origin_kind = 'user_correction' AND source_available = true "
            "AND source_conversation_id IS NULL AND source_user_message_id IS NULL "
            "AND source_assistant_message_id IS NULL "
            "AND source_generation_attempt_id IS NULL "
            "AND source_generation_status IS NULL "
            "AND superseded_revision_id IS NOT NULL AND corrected_at IS NOT NULL)",
            name="ck_memory_origin",
        ),
        CheckConstraint(
            "superseded_revision_id IS NULL OR superseded_revision_id != revision_id",
            name="ck_memory_not_self_correction",
        ),
        Index(
            "uq_memory_current_lineage",
            "memory_id",
            unique=True,
            postgresql_where=text("lifecycle != 'superseded'"),
            sqlite_where=text("lifecycle != 'superseded'"),
        ),
        Index(
            "uq_memory_current_subject",
            "subject",
            unique=True,
            postgresql_where=text("lifecycle != 'superseded'"),
            sqlite_where=text("lifecycle != 'superseded'"),
        ),
        Index("ix_memory_eligible_order", "lifecycle", "created_at", "revision_id"),
    )

    revision_id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, doc="Unique identifier for this revision."
    )
    memory_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
        doc="Stable identifier shared by every revision in the lineage.",
    )
    subject: Mapped[str] = mapped_column(
        Text, nullable=False, doc="Normalized subject used for conflict detection."
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, doc="Normalized durable memory statement."
    )
    lifecycle: Mapped[MemoryLifecycle] = mapped_column(
        SqlEnum(
            MemoryLifecycle,
            name="memorylifecycle",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        doc="Lifecycle state of this revision.",
    )
    origin_kind: Mapped[MemoryOriginKind] = mapped_column(
        SqlEnum(
            MemoryOriginKind,
            name="memoryoriginkind",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        doc="Kind of provenance recorded for this revision.",
    )
    source_available: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        doc="Whether extracted source records remain available.",
    )
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        nullable=True, doc="Conversation from which this revision was extracted."
    )
    source_user_message_id: Mapped[UUID | None] = mapped_column(
        nullable=True, doc="User message from which this revision was extracted."
    )
    source_assistant_message_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        doc="Assistant message completing the extracted source turn.",
    )
    source_generation_attempt_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        doc="Completed attempt from which this revision was extracted.",
    )
    source_generation_status: Mapped[GenerationAttemptStatus | None] = mapped_column(
        SqlEnum(
            GenerationAttemptStatus,
            name="generationattemptstatus",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
            create_type=False,
        ),
        nullable=True,
        doc="Completed status used to constrain extraction provenance.",
    )
    superseded_revision_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        doc="Prior revision explicitly replaced by a user correction.",
    )
    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Time at which a user authored this correction.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Time at which this revision was created.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Time at which this revision last changed lifecycle.",
    )

    source_attempt: Mapped[GenerationAttempt | None] = relationship(
        foreign_keys=[
            source_generation_attempt_id,
            source_conversation_id,
            source_user_message_id,
            source_assistant_message_id,
            source_generation_status,
        ],
        doc="Completed attempt that supplied extracted provenance.",
    )
    superseded_revision: Mapped[Memory | None] = relationship(
        remote_side=[revision_id],
        foreign_keys=[superseded_revision_id],
        doc="Revision explicitly replaced by this user correction.",
    )


class ExtractionReceipt(ChatBase):
    """Represents terminal memory processing for one completed attempt."""

    __tablename__ = "memory_extraction_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation_attempt_id", "generation_attempt_status"],
            [
                f"{CHAT_SCHEMA}.generation_attempts.id",
                f"{CHAT_SCHEMA}.generation_attempts.status",
            ],
            name="fk_extraction_receipt_completed_attempt",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "generation_attempt_status = 'completed'",
            name="ck_extraction_receipt_completed_attempt",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 1 AND 3",
            name="ck_extraction_receipt_attempt_count",
        ),
        CheckConstraint(
            "outcome != 'exhausted' OR attempt_count = 3",
            name="ck_extraction_receipt_exhausted_count",
        ),
    )

    generation_attempt_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        doc="Completed attempt processed exactly once to a terminal outcome.",
    )
    generation_attempt_status: Mapped[GenerationAttemptStatus] = mapped_column(
        SqlEnum(
            GenerationAttemptStatus,
            name="generationattemptstatus",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
            create_type=False,
        ),
        nullable=False,
        default=GenerationAttemptStatus.COMPLETED,
        doc="Completed status used to constrain receipt ownership.",
    )
    outcome: Mapped[MemoryExtractionOutcome] = mapped_column(
        SqlEnum(
            MemoryExtractionOutcome,
            name="memoryextractionoutcome",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        doc="Terminal outcome of bounded extraction processing.",
    )
    attempt_count: Mapped[int] = mapped_column(
        nullable=False,
        doc="Number of processing attempts consumed before termination.",
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Time at which extraction processing became terminal.",
    )

    generation_attempt: Mapped[GenerationAttempt] = relationship(
        foreign_keys=[generation_attempt_id, generation_attempt_status],
        doc="Completed attempt represented by this terminal receipt.",
    )
