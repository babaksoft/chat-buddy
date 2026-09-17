from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chat_buddy.chat.infrastructure.db.base import ChatBase

if TYPE_CHECKING:
    from chat_buddy.chat.infrastructure.db.models.generation_attempt import (
        GenerationAttempt,
    )
    from chat_buddy.chat.infrastructure.db.models.message import Message


class Conversation(ChatBase):
    """Represents a persisted conversation and its generation defaults."""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the conversation.",
    )

    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Optional user-visible title for the conversation.",
    )

    provider_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Stable identifier of the selected response provider.",
    )

    model_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Stable provider-local identifier of the selected response model.",
    )

    requested_generation_configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        doc="Provider-neutral generation defaults requested for the next attempt.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        doc="Time at which the conversation was created.",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        doc="Time at which the conversation was last updated.",
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        doc="Messages persisted as the conversation's ordinary history.",
    )

    attempts: Mapped[list[GenerationAttempt]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        doc="Response-generation attempts associated with the conversation.",
    )
