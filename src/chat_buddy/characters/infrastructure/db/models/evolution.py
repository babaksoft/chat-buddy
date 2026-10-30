"""Append-only evolution history and rebuildable projection caches."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db import CharactersBase


class EvolutionEffectModel(CharactersBase):
    """Store one idempotent processing audit record per persona checkpoint."""

    __tablename__ = "evolution_effects"
    __table_args__ = (
        UniqueConstraint("id", "continuity_id", name="uq_evolution_effect_ownership"),
        UniqueConstraint(
            "source_persona_message_id", name="uq_evolution_effect_source"
        ),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_evolution_effect_owner",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_evolution_effect_conversation",
        ),
        ForeignKeyConstraint(
            ["source_persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_evolution_effect_source",
        ),
        CheckConstraint(
            "state IN ('reserved', 'no_change', 'applied', 'rejected')",
            name="ck_evolution_effect_state",
        ),
        CheckConstraint(
            "(state = 'reserved' AND proposal IS NULL AND decision IS NULL AND completed_at IS NULL) OR "
            "(state <> 'reserved' AND proposal IS NOT NULL AND decision IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_evolution_effect_terminal",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable effect identifier."
    )
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning continuity.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    conversation_id: Mapped[UUID] = mapped_column(Uuid, doc="Source conversation.")
    source_persona_message_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Unique source persona checkpoint."
    )
    source: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Exact source evidence reference."
    )
    state: Mapped[str] = mapped_column(String(16), doc="Processing lifecycle state.")
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Configuration fixed at reservation."
    )
    proposal: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), doc="Bounded terminal proposal audit data."
    )
    decision: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), doc="Terminal application decision audit data."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC reservation timestamp."
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), doc="UTC terminal commit timestamp."
    )


class EvolutionEventModel(CharactersBase):
    """Store one immutable accepted command in append order."""

    __tablename__ = "evolution_events"
    __table_args__ = (
        UniqueConstraint("id", "continuity_id", name="uq_evolution_event_ownership"),
        UniqueConstraint(
            "effect_id", "position", name="uq_evolution_event_effect_position"
        ),
        UniqueConstraint(
            "continuity_id",
            "relationship_revision",
            "adaptation_revision",
            name="uq_evolution_event_replay_position",
        ),
        ForeignKeyConstraint(
            ["effect_id", "continuity_id"],
            [
                "characters.evolution_effects.id",
                "characters.evolution_effects.continuity_id",
            ],
            name="fk_evolution_event_effect",
            ondelete="CASCADE",
        ),
        CheckConstraint("position > 0", name="ck_evolution_event_position"),
        CheckConstraint(
            "relationship_revision >= 0 AND adaptation_revision >= 0",
            name="ck_evolution_event_revisions",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, doc="Stable event ID.")
    effect_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning terminal effect.")
    proposal_id: Mapped[UUID] = mapped_column(Uuid, doc="Accepted proposal ID.")
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning continuity.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    position: Mapped[int] = mapped_column(Integer, doc="Order within the proposal.")
    command: Mapped[dict[str, Any]] = mapped_column(JSON, doc="Accepted typed command.")
    relationship_revision: Mapped[int] = mapped_column(
        Integer, doc="Relationship revision after this event."
    )
    adaptation_revision: Mapped[int] = mapped_column(
        Integer, doc="Adaptation revision after this event."
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Exact strategy and policy provenance."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC event timestamp."
    )


class EvolutionCorrectionEventModel(CharactersBase):
    """Store one append-only user interpretation of an inferred event."""

    __tablename__ = "evolution_correction_events"
    __table_args__ = (
        UniqueConstraint(
            "id", "continuity_id", name="uq_evolution_correction_ownership"
        ),
        UniqueConstraint(
            "continuity_id",
            "relationship_revision",
            "adaptation_revision",
            name="uq_evolution_correction_replay_position",
        ),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_evolution_correction_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_event_id", "continuity_id"],
            [
                "characters.evolution_events.id",
                "characters.evolution_events.continuity_id",
            ],
            name="fk_evolution_correction_target",
        ),
        CheckConstraint(
            "action IN ('exclude', 'replace', 'restore')",
            name="ck_evolution_correction_action",
        ),
        CheckConstraint(
            "(action = 'replace' AND replacement IS NOT NULL) OR "
            "(action <> 'replace' AND replacement IS NULL)",
            name="ck_evolution_correction_replacement",
        ),
        CheckConstraint(
            "expected_relationship_revision >= 0 AND "
            "expected_adaptation_revision >= 0 AND "
            "relationship_revision >= 0 AND adaptation_revision >= 0",
            name="ck_evolution_correction_revisions",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, doc="Stable event ID.")
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning continuity.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    target_event_id: Mapped[UUID] = mapped_column(Uuid, doc="Corrected inferred event.")
    action: Mapped[str] = mapped_column(String(16), doc="Correction operation.")
    replacement: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), doc="User-authored replacement command."
    )
    note: Mapped[str] = mapped_column(
        String(1024), doc="User-authored correction provenance."
    )
    expected_relationship_revision: Mapped[int] = mapped_column(
        Integer, doc="Observed relationship projection revision."
    )
    expected_adaptation_revision: Mapped[int] = mapped_column(
        Integer, doc="Observed adaptation projection revision."
    )
    relationship_revision: Mapped[int] = mapped_column(
        Integer, doc="Relationship revision after this correction."
    )
    adaptation_revision: Mapped[int] = mapped_column(
        Integer, doc="Adaptation revision after this correction."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC correction timestamp."
    )


class RelationshipProjectionModel(CharactersBase):
    """Cache the current relationship projection for one continuity."""

    __tablename__ = "relationship_projections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_relationship_projection_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["rebuild_checkpoint_id", "continuity_id"],
            [
                "characters.evolution_events.id",
                "characters.evolution_events.continuity_id",
            ],
            name="fk_relationship_projection_checkpoint",
            use_alter=True,
        ),
        CheckConstraint("revision >= 0", name="ck_relationship_projection_revision"),
    )

    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, doc="Unique owning continuity."
    )
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    revision: Mapped[int] = mapped_column(Integer, doc="Current replay revision.")
    rebuild_checkpoint_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Last event represented by this cache."
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Validated current relationship projection."
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC latest cache update."
    )


class PersonaAdaptationProjectionModel(CharactersBase):
    """Cache current continuity-local persona adaptations."""

    __tablename__ = "persona_adaptation_projections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_adaptation_projection_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["rebuild_checkpoint_id", "continuity_id"],
            [
                "characters.evolution_events.id",
                "characters.evolution_events.continuity_id",
            ],
            name="fk_adaptation_projection_checkpoint",
            use_alter=True,
        ),
        CheckConstraint("revision >= 0", name="ck_adaptation_projection_revision"),
    )

    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, doc="Unique owning continuity."
    )
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    revision: Mapped[int] = mapped_column(Integer, doc="Current replay revision.")
    rebuild_checkpoint_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Last event represented by this cache."
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Validated current adaptation projection."
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC latest cache update."
    )
