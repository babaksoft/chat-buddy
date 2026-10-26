"""Characters-only continuity, conversation, and starting-state ownership."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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
        UniqueConstraint(
            "id",
            "identity_id",
            "persona_id",
            "mode",
            name="uq_continuity_mode_ownership",
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
        Index(
            "uq_active_storyline_pair",
            "identity_id",
            "persona_id",
            unique=True,
            postgresql_where=text("mode = 'storyline' AND lifecycle = 'active'"),
            sqlite_where=text("mode = 'storyline' AND lifecycle = 'active'"),
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
    """Persist one mode-owned conversation and its selected graph leaf."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "continuity_id", name="uq_conversation_scope"),
        UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            "mode",
            name="uq_conversation_complete_ownership",
        ),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id", "mode"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
                "characters.continuities.mode",
            ],
            name="fk_conversation_ownership",
        ),
        CheckConstraint(
            "mode IN ('ongoing', 'storyline')", name="ck_conversation_mode"
        ),
        Index(
            "uq_ongoing_continuity_conversation",
            "continuity_id",
            unique=True,
            postgresql_where=text("mode = 'ongoing'"),
            sqlite_where=text("mode = 'ongoing'"),
        ),
        ForeignKeyConstraint(
            ["selected_leaf_id", "id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_conversation_selected_leaf",
            use_alter=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
        doc="Stable mode-owned conversation identifier.",
    )
    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Owning continuity identifier."
    )
    identity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Identity matching continuity ownership."
    )
    persona_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Persona matching continuity ownership."
    )
    mode: Mapped[str] = mapped_column(
        String(16), default="ongoing", doc="Mode matching continuity ownership."
    )

    generation_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, doc="Requested provider model and defaults for future attempts."
    )
    selected_leaf_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Currently selected message graph leaf."
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


class StorylineModel(CharactersBase):
    """Persist Storyline metadata and the optimistic mutation revision."""

    __tablename__ = "storylines"
    __table_args__ = (
        UniqueConstraint(
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_storyline_ownership",
        ),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id", "mode"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
                "characters.continuities.mode",
            ],
            name="fk_storyline_continuity",
        ),
        CheckConstraint("mode = 'storyline'", name="ck_storyline_mode"),
        CheckConstraint("revision >= 1", name="ck_storyline_revision"),
    )

    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, doc="Owning Storyline continuity."
    )
    identity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Identity matching continuity ownership."
    )
    persona_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Persona matching continuity ownership."
    )
    mode: Mapped[str] = mapped_column(
        String(16), default="storyline", doc="Fixed Storyline mode discriminator."
    )
    name: Mapped[str] = mapped_column(String(128), doc="User-authored Storyline name.")
    revision: Mapped[int] = mapped_column(
        Integer, default=1, doc="Optimistic Storyline mutation revision."
    )
    fork_provenance: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, doc="Optional source-to-copy mapping for a reviewed fork."
    )


class SceneModel(CharactersBase):
    """Persist ordered Storyline scene metadata and conversation ownership."""

    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_scene_ownership",
        ),
        UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            "conversation_id",
            name="uq_scene_complete_ownership",
        ),
        UniqueConstraint(
            "continuity_id", "position", name="uq_scene_storyline_position"
        ),
        UniqueConstraint("conversation_id", name="uq_scene_conversation"),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.storylines.continuity_id",
                "characters.storylines.identity_id",
                "characters.storylines.persona_id",
            ],
            name="fk_scene_storyline_ownership",
        ),
        ForeignKeyConstraint(
            [
                "conversation_id",
                "continuity_id",
                "identity_id",
                "persona_id",
                "mode",
            ],
            [
                "characters.conversations.id",
                "characters.conversations.continuity_id",
                "characters.conversations.identity_id",
                "characters.conversations.persona_id",
                "characters.conversations.mode",
            ],
            name="fk_scene_conversation_ownership",
        ),
        CheckConstraint("mode = 'storyline'", name="ck_scene_mode"),
        CheckConstraint("position >= 1", name="ck_scene_position"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable scene identifier."
    )
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning Storyline.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Independent owned scene conversation."
    )
    mode: Mapped[str] = mapped_column(
        String(16), default="storyline", doc="Fixed Storyline mode discriminator."
    )
    position: Mapped[int] = mapped_column(
        Integer, doc="Immutable one-based chronological position."
    )
    title: Mapped[str] = mapped_column(String(128), doc="Presentation-only title.")
    setup: Mapped[str] = mapped_column(String(8192), doc="Authored scene situation.")
    response_style: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Fixed Stage 6 response-style snapshot."
    )
    setup_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="Whether first user input froze setup."
    )
