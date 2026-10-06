"""Ownership-constrained immutable rolling-summary revisions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db import CharactersBase


class SummaryRevisionModel(CharactersBase):
    """Store one immutable summary lineage revision."""

    __tablename__ = "summary_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_summary_conversation",
        ),
        ForeignKeyConstraint(
            ["checkpoint_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_summary_checkpoint",
        ),
        ForeignKeyConstraint(
            ["predecessor_id", "conversation_id", "continuity_id"],
            [
                "characters.summary_revisions.id",
                "characters.summary_revisions.conversation_id",
                "characters.summary_revisions.continuity_id",
            ],
            name="fk_summary_predecessor",
        ),
        UniqueConstraint(
            "id", "conversation_id", "continuity_id", name="uq_summary_ownership"
        ),
        UniqueConstraint(
            "conversation_id",
            "checkpoint_message_id",
            name="uq_summary_checkpoint",
        ),
        CheckConstraint("revision > 0", name="ck_summary_revision"),
        CheckConstraint("length(content) > 0", name="ck_summary_content"),
        Index("ix_summary_conversation_revision", "conversation_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, doc="Stable revision.")
    conversation_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning conversation.")
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning continuity.")
    revision: Mapped[int] = mapped_column(Integer, doc="Monotonic lineage position.")
    predecessor_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Prior summary revision."
    )
    checkpoint_message_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Last covered persona message."
    )
    content: Mapped[str] = mapped_column(Text, doc="Generated summary content.")
    generation: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Effective summary generation provenance."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC creation timestamp."
    )
