"""Ownership-constrained append-only messages and generation ledger."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db import CharactersBase


class MessageModel(CharactersBase):
    """Store committed sole-path messages, never partial provider output."""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_message_conversation",
        ),
        UniqueConstraint(
            "id", "conversation_id", "continuity_id", name="uq_message_ownership"
        ),
        UniqueConstraint("conversation_id", "sequence", name="uq_message_sequence"),
        UniqueConstraint("reply_to", name="uq_message_response"),
        ForeignKeyConstraint(
            ["reply_to", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_message_reply",
        ),
        CheckConstraint(
            "sequence > 0 AND ((role = 'user' AND sequence % 2 = 1 AND reply_to IS NULL) OR (role = 'persona' AND sequence % 2 = 0 AND reply_to IS NOT NULL))",
            name="ck_message_path",
        ),
        CheckConstraint("length(content) > 0", name="ck_message_content"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable message identifier."
    )
    conversation_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning conversation.")
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning continuity.")
    sequence: Mapped[int] = mapped_column(Integer, doc="Deterministic path position.")
    role: Mapped[str] = mapped_column(String(16), doc="User or persona speaker.")
    content: Mapped[str] = mapped_column(Text, doc="Exact committed text.")
    reply_to: Mapped[UUID | None] = mapped_column(
        Uuid, doc="User message completed by this response."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC commit timestamp."
    )


class GenerationAttemptModel(CharactersBase):
    """Retain every effective generation and incomplete output independently."""

    __tablename__ = "generation_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_attempt_conversation",
        ),
        ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_attempt_user",
        ),
        ForeignKeyConstraint(
            ["persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_attempt_persona",
        ),
        UniqueConstraint("persona_message_id", name="uq_attempt_completion"),
        CheckConstraint(
            "status IN ('pending', 'streaming', 'completed', 'failed', 'interrupted')",
            name="ck_attempt_status",
        ),
        CheckConstraint(
            "(status = 'completed' AND persona_message_id IS NOT NULL) OR (status <> 'completed' AND persona_message_id IS NULL)",
            name="ck_attempt_completion",
        ),
        CheckConstraint(
            "(status IN ('pending', 'streaming') AND finished_at IS NULL) OR (status IN ('completed', 'failed', 'interrupted') AND finished_at IS NOT NULL)",
            name="ck_attempt_terminal",
        ),
        Index(
            "uq_open_conversation_attempt",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'streaming')"),
            sqlite_where=text("status IN ('pending', 'streaming')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable attempt identifier."
    )
    conversation_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning conversation.")
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning continuity.")
    user_message_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Existing unmatched input message."
    )
    persona_message_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Atomically committed response identifier."
    )
    submitted_input: Mapped[str] = mapped_column(
        Text, doc="Exact submitted input provenance."
    )
    generation: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Immutable effective provider model and configuration."
    )
    status: Mapped[str] = mapped_column(String(16), doc="Attempt lifecycle.")
    incomplete_output: Mapped[str] = mapped_column(
        Text, default="", doc="Output separate from committed history."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC submission timestamp."
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC latest progress heartbeat."
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), doc="UTC terminal timestamp."
    )
