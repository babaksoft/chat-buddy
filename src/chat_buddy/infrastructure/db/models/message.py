from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chat_buddy.domain.chat import ChatRole
from chat_buddy.infrastructure.db.base import Base

if TYPE_CHECKING:
    from chat_buddy.infrastructure.db.models.conversation import Conversation


class Message(Base):
    """Represents a single message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
    )

    role: Mapped[ChatRole] = mapped_column(
        SqlEnum(
            ChatRole,
            name="messagerole",
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    conversation: Mapped[Conversation] = relationship(
        back_populates="messages",
    )
