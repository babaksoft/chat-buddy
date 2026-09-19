from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chat_buddy.chat.domain import ChatRole
from chat_buddy.chat.infrastructure.db.base import CHAT_SCHEMA, ChatBase

if TYPE_CHECKING:
    from chat_buddy.chat.infrastructure.db.models.conversation import Conversation


class Message(ChatBase):
    """Represents a persisted message within conversation history."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "conversation_id",
            name="uq_message_id_conversation",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the message.",
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CHAT_SCHEMA}.conversations.id"),
        nullable=False,
        doc="Identifier of the conversation that owns the message.",
    )

    role: Mapped[ChatRole] = mapped_column(
        SqlEnum(
            ChatRole,
            name="messagerole",
            inherit_schema=True,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        doc="Role of the message author within the conversation.",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Text content of the message.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        doc="Time at which the message was created.",
    )

    conversation: Mapped[Conversation] = relationship(
        back_populates="messages",
        doc="Conversation that owns the message.",
    )
