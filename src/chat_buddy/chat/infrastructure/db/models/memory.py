from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.chat.infrastructure.db.base import ChatBase


class Memory(ChatBase):
    """Represents a persisted keyed Chat memory."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        doc="Unique identifier for the memory.",
    )

    key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        doc="Stable unique key identifying the memory.",
    )

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Stored text value of the memory.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Time at which the memory was created.",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Time at which the memory was last updated.",
    )

    def __repr__(self) -> str:
        """
        Return a developer-friendly representation.

        Returns:
            Developer-friendly representation of this object.
        """

        return f"Memory(id={self.id!r}, key={self.key!r})"
