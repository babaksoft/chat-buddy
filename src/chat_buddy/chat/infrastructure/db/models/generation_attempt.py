from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chat_buddy.chat.domain import GenerationAttemptStatus
from chat_buddy.chat.infrastructure.db.base import CHAT_SCHEMA, ChatBase

if TYPE_CHECKING:
    from chat_buddy.chat.infrastructure.db.models.conversation import Conversation


class GenerationAttempt(ChatBase):
    """Represents persisted generation provenance and lifecycle state."""

    __tablename__ = "generation_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_user_message_id", "conversation_id"],
            [f"{CHAT_SCHEMA}.messages.id", f"{CHAT_SCHEMA}.messages.conversation_id"],
            name="fk_generation_attempt_source_conversation",
        ),
        ForeignKeyConstraint(
            ["assistant_message_id", "conversation_id"],
            [f"{CHAT_SCHEMA}.messages.id", f"{CHAT_SCHEMA}.messages.conversation_id"],
            name="fk_generation_attempt_assistant_conversation",
        ),
        UniqueConstraint(
            "id",
            "status",
            name="uq_generation_attempt_id_status",
        ),
        UniqueConstraint(
            "id",
            "conversation_id",
            "source_user_message_id",
            "assistant_message_id",
            "status",
            name="uq_generation_attempt_memory_source",
        ),
        Index(
            "uq_generation_attempt_open_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'streaming')"),
            sqlite_where=text("status IN ('pending', 'streaming')"),
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) "
            "OR (status = 'streaming' AND started_at IS NOT NULL "
            "AND finished_at IS NULL) OR (status IN ('completed', 'failed', "
            "'interrupted') AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_generation_attempt_lifecycle_timestamps",
        ),
        CheckConstraint(
            "(status = 'completed' AND assistant_message_id IS NOT NULL "
            "AND partial_content IS NULL) OR "
            "(status != 'completed' AND assistant_message_id IS NULL)",
            name="ck_generation_attempt_completed_message",
        ),
        CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL) OR "
            "(status != 'failed' AND error_code IS NULL AND error_detail IS NULL)",
            name="ck_generation_attempt_failure_information",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the generation attempt.",
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CHAT_SCHEMA}.conversations.id"),
        nullable=False,
        index=True,
        doc="Identifier of the conversation that owns the attempt.",
    )
    source_user_message_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
        doc="Identifier of the user message that prompted the attempt.",
    )
    submitted_user_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Immutable user content submitted for this invocation.",
    )
    provider_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Stable identifier of the response provider used by the attempt.",
    )
    model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Stable provider-local identifier of the response model used.",
    )
    effective_configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        doc="Immutable provider-neutral configuration used by the attempt.",
    )
    status: Mapped[GenerationAttemptStatus] = mapped_column(
        SqlEnum(
            GenerationAttemptStatus,
            name="generationattemptstatus",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        doc="Current lifecycle status of the attempt.",
    )
    partial_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Latest recoverable incomplete response content.",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Normalized safe failure code for a failed attempt.",
    )
    error_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Optional safe user-facing detail for a failed attempt.",
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        unique=True,
        doc="Identifier of the assistant message produced on completion.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Time at which the attempt was created.",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Time at which response streaming started.",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Time at which the attempt reached a terminal state.",
    )

    conversation: Mapped[Conversation] = relationship(
        back_populates="attempts",
        doc="Conversation that owns the attempt.",
    )
