from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKeyConstraint, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chat_buddy.chat.domain import SummaryLifecycle
from chat_buddy.chat.infrastructure.db.base import CHAT_SCHEMA, ChatBase

if TYPE_CHECKING:
    from chat_buddy.chat.infrastructure.db.models.message import Message


class Summary(ChatBase):
    """Represents one persisted version of a conversation summary."""

    __tablename__ = "summaries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id"],
            [f"{CHAT_SCHEMA}.conversations.id"],
            name="fk_summary_conversation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["checkpoint_message_id", "conversation_id"],
            [f"{CHAT_SCHEMA}.messages.id", f"{CHAT_SCHEMA}.messages.conversation_id"],
            name="fk_summary_checkpoint_conversation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["predecessor_id", "conversation_id"],
            [f"{CHAT_SCHEMA}.summaries.id", f"{CHAT_SCHEMA}.summaries.conversation_id"],
            name="fk_summary_predecessor_conversation",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "predecessor_id IS NULL OR predecessor_id != id",
            name="ck_summary_not_own_predecessor",
        ),
        UniqueConstraint("id", "conversation_id", name="uq_summary_id_conversation"),
        Index(
            "uq_summary_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("lifecycle = 'active'"),
            sqlite_where=text("lifecycle = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the summary version.",
    )
    conversation_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
        doc="Identifier of the conversation that owns the summary.",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Validated text of the summary version.",
    )
    lifecycle: Mapped[SummaryLifecycle] = mapped_column(
        SqlEnum(
            SummaryLifecycle,
            name="summarylifecycle",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        doc="Current lifecycle state of the summary version.",
    )
    predecessor_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        doc="Identifier of the immediately preceding summary version.",
    )
    checkpoint_message_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
        doc="Newest assistant message incorporated into the summary.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Time at which the summary version was created.",
    )

    checkpoint_message: Mapped[Message] = relationship(
        foreign_keys=[checkpoint_message_id, conversation_id],
        viewonly=True,
        doc="Assistant message defining the summary checkpoint.",
    )
    predecessor: Mapped[Summary | None] = relationship(
        remote_side=[id, conversation_id],
        foreign_keys=[predecessor_id, conversation_id],
        viewonly=True,
        doc="Immediately preceding summary version, when present.",
    )
