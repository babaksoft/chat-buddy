from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.infrastructure.db.base import Base


class Memory(Base):
    """Represents a persistent user memory."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)

    key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        """
        Return a developer-friendly representation.

        Returns:
            Developer-friendly representation of this object.
        """

        return f"Memory(id={self.id!r}, key={self.key!r})"
