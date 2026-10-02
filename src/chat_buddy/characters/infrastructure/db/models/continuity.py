"""Characters-only continuity, conversation, and starting-state ownership."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db import CharactersBase


class ContinuityModel(CharactersBase):
    """Persist permanent profile bindings and confirmation provenance."""

    __tablename__ = "continuities"
    __table_args__ = (
        UniqueConstraint(
            "id", "identity_id", "persona_id", name="uq_continuity_ownership"
        ),
        CheckConstraint(
            "mode IN ('ongoing', 'storyline', 'timeline')", name="ck_continuity_mode"
        ),
        CheckConstraint(
            "lifecycle IN ('active', 'archived')", name="ck_continuity_lifecycle"
        ),
        Index(
            "uq_active_ongoing_pair",
            "identity_id",
            "persona_id",
            unique=True,
            postgresql_where=text("mode = 'ongoing' AND lifecycle = 'active'"),
            sqlite_where=text("mode = 'ongoing' AND lifecycle = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable continuity identifier."
    )
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.identities.id"), doc="Permanent identity owner."
    )
    persona_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.personas.id"), doc="Permanent persona owner."
    )
    mode: Mapped[str] = mapped_column(String(16), doc="Permanent continuity mode.")
    lifecycle: Mapped[str] = mapped_column(
        String(16), doc="Writable or permanently archived lifecycle."
    )
    request_id: Mapped[UUID] = mapped_column(
        Uuid, unique=True, doc="Unique confirmed start identifier."
    )
    confirmed_request: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Full reviewed request for idempotency comparison."
    )


class ConversationModel(CharactersBase):
    """Persist the sole Ongoing conversation with matching profile ownership."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "continuity_id", name="uq_conversation_scope"),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_conversation_ownership",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
        doc="Stable sole conversation identifier.",
    )
    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, unique=True, doc="Unique owning Ongoing continuity."
    )
    identity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Identity matching continuity ownership."
    )
    persona_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Persona matching continuity ownership."
    )

    generation_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, doc="Requested provider model and defaults for future attempts."
    )


class StartingRelationshipModel(CharactersBase):
    """Persist one immutable qualitative starting snapshot per continuity."""

    __tablename__ = "starting_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_starting_relationship_ownership",
        ),
    )

    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, doc="Unique owning continuity."
    )
    identity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Identity matching continuity ownership."
    )
    persona_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Persona matching continuity ownership."
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Validated qualitative starting values and per-field origins."
    )
