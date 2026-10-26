"""Characters-owned Storyline memory and extraction persistence models."""

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
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db import CharactersBase


class StorylineMemoryModel(CharactersBase):
    """Persist one logical memory and its sole current revision pointer."""

    __tablename__ = "storyline_memories"
    __table_args__ = (
        UniqueConstraint("id", "continuity_id", name="uq_storyline_memory_ownership"),
        UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_storyline_memory_complete_ownership",
        ),
        UniqueConstraint(
            "continuity_id",
            "subject_key",
            name="uq_storyline_memory_subject",
        ),
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.storylines.continuity_id",
                "characters.storylines.identity_id",
                "characters.storylines.persona_id",
            ],
            name="fk_storyline_memory_owner",
        ),
        ForeignKeyConstraint(
            ["current_revision_id", "id", "continuity_id"],
            [
                "characters.memory_revisions.id",
                "characters.memory_revisions.memory_id",
                "characters.memory_revisions.continuity_id",
            ],
            name="fk_storyline_memory_current_revision",
            use_alter=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable logical-memory identifier."
    )
    continuity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Owning Storyline continuity."
    )
    identity_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Identity matching Storyline ownership."
    )
    persona_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Persona matching Storyline ownership."
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Sole current revision after lineage creation."
    )
    subject_key: Mapped[str] = mapped_column(
        String(256), doc="Case-folded current subject used for collision checks."
    )


class MemoryEvidenceModel(CharactersBase):
    """Persist exact source-turn and extraction provenance for one assertion."""

    __tablename__ = "memory_evidence"
    __table_args__ = (
        UniqueConstraint("id", "continuity_id", name="uq_memory_evidence_owner"),
        UniqueConstraint(
            "id",
            "memory_id",
            "continuity_id",
            name="uq_memory_evidence_lineage_owner",
        ),
        UniqueConstraint(
            "memory_id",
            "source_persona_message_id",
            name="uq_memory_evidence_source_turn",
        ),
        ForeignKeyConstraint(
            ["memory_id", "continuity_id", "identity_id", "persona_id"],
            [
                "characters.storyline_memories.id",
                "characters.storyline_memories.continuity_id",
                "characters.storyline_memories.identity_id",
                "characters.storyline_memories.persona_id",
            ],
            name="fk_memory_evidence_memory",
            ondelete="CASCADE",
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
            name="fk_memory_evidence_conversation",
        ),
        ForeignKeyConstraint(
            [
                "scene_id",
                "continuity_id",
                "identity_id",
                "persona_id",
                "conversation_id",
            ],
            [
                "characters.scenes.id",
                "characters.scenes.continuity_id",
                "characters.scenes.identity_id",
                "characters.scenes.persona_id",
                "characters.scenes.conversation_id",
            ],
            name="fk_memory_evidence_scene",
        ),
        ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_memory_evidence_user_message",
        ),
        ForeignKeyConstraint(
            ["source_persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_memory_evidence_persona_message",
        ),
        ForeignKeyConstraint(
            ["occurrence_scene_id", "continuity_id", "identity_id", "persona_id"],
            [
                "characters.scenes.id",
                "characters.scenes.continuity_id",
                "characters.scenes.identity_id",
                "characters.scenes.persona_id",
            ],
            name="fk_memory_evidence_occurrence_scene",
        ),
        CheckConstraint("mode = 'storyline'", name="ck_memory_evidence_mode"),
        CheckConstraint(
            "purpose IN ('support', 'conflict')", name="ck_memory_evidence_purpose"
        ),
        CheckConstraint(
            "persona_checkpoint > 0 AND persona_checkpoint % 2 = 0",
            name="ck_memory_evidence_checkpoint",
        ),
        CheckConstraint(
            "occurrence_position > 0 AND learned_position > 0 AND occurrence_position <= learned_position",
            name="ck_memory_evidence_temporal_positions",
        ),
        CheckConstraint(
            "learned_scene_id = scene_id",
            name="ck_memory_evidence_learned_scene",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable evidence-link identifier."
    )
    memory_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Supported logical memory, absent for targetless conflicts."
    )
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning Storyline.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Source scene conversation."
    )
    mode: Mapped[str] = mapped_column(
        String(16), default="storyline", doc="Fixed Storyline mode discriminator."
    )
    purpose: Mapped[str] = mapped_column(
        String(16), doc="Supporting or conflict evidence classification."
    )
    scene_id: Mapped[UUID] = mapped_column(Uuid, doc="Source scene identifier.")
    user_message_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Source turn user-message identifier."
    )
    source_persona_message_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Source turn persona-message checkpoint."
    )
    persona_checkpoint: Mapped[int] = mapped_column(
        Integer, doc="Even selected-path checkpoint position."
    )
    occurrence_scene_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Scene where the remembered assertion occurred."
    )
    occurrence_position: Mapped[int] = mapped_column(
        Integer, doc="Chronological occurrence scene position."
    )
    learned_scene_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Source scene where the assertion was learned."
    )
    learned_position: Mapped[int] = mapped_column(
        Integer, doc="Chronological learned scene position."
    )
    extraction: Mapped[dict[str, Any]] = mapped_column(
        JSON, doc="Immutable selector extractor prompt and model provenance."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC evidence-link creation time."
    )


class MemoryRevisionModel(CharactersBase):
    """Persist one immutable revision in a logical-memory lineage."""

    __tablename__ = "memory_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id", "memory_id", "continuity_id", name="uq_memory_revision_owner"
        ),
        UniqueConstraint("memory_id", "revision", name="uq_memory_revision_position"),
        Index(
            "uq_memory_current_revision",
            "memory_id",
            unique=True,
            postgresql_where=text("state IN ('active', 'excluded')"),
            sqlite_where=text("state IN ('active', 'excluded')"),
        ),
        ForeignKeyConstraint(
            ["memory_id", "continuity_id"],
            [
                "characters.storyline_memories.id",
                "characters.storyline_memories.continuity_id",
            ],
            name="fk_memory_revision_memory",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["predecessor_id", "memory_id", "continuity_id"],
            [
                "characters.memory_revisions.id",
                "characters.memory_revisions.memory_id",
                "characters.memory_revisions.continuity_id",
            ],
            name="fk_memory_revision_predecessor",
        ),
        ForeignKeyConstraint(
            ["source_evidence_id", "memory_id", "continuity_id"],
            [
                "characters.memory_evidence.id",
                "characters.memory_evidence.memory_id",
                "characters.memory_evidence.continuity_id",
            ],
            name="fk_memory_revision_source",
        ),
        CheckConstraint("revision > 0", name="ck_memory_revision_position"),
        CheckConstraint(
            "state IN ('active', 'excluded', 'superseded')",
            name="ck_memory_revision_state",
        ),
        CheckConstraint(
            "authorship IN ('extracted', 'user')",
            name="ck_memory_revision_authorship",
        ),
        CheckConstraint(
            "kind IN ('extraction', 'automatic_supersede', 'user_correction', 'exclusion', 'reactivation')",
            name="ck_memory_revision_kind",
        ),
        CheckConstraint(
            "(revision = 1 AND predecessor_id IS NULL AND kind = 'extraction' AND authorship = 'extracted') OR (revision > 1 AND predecessor_id IS NOT NULL AND kind <> 'extraction')",
            name="ck_memory_revision_origin",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable revision identifier."
    )
    memory_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning logical memory.")
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning Storyline.")
    revision: Mapped[int] = mapped_column(
        Integer, doc="Positive consecutive lineage position."
    )
    predecessor_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Immediately preceding revision."
    )
    subject: Mapped[str] = mapped_column(
        String(256), doc="User-readable normalized fact subject."
    )
    content: Mapped[str] = mapped_column(
        String(4096), doc="Complete remembered assertion."
    )
    state: Mapped[str] = mapped_column(String(16), doc="Revision lifecycle state.")
    authorship: Mapped[str] = mapped_column(String(16), doc="Content authority.")
    kind: Mapped[str] = mapped_column(String(32), doc="Revision creation operation.")
    source_evidence_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Originating evidence retained through transitions."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC revision creation time."
    )


class MemoryExtractionEffectModel(CharactersBase):
    """Persist the idempotent extraction outcome for one persona checkpoint."""

    __tablename__ = "memory_extraction_effects"
    __table_args__ = (
        UniqueConstraint(
            "source_persona_message_id", name="uq_memory_effect_source_message"
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
            name="fk_memory_effect_conversation",
        ),
        ForeignKeyConstraint(
            [
                "scene_id",
                "continuity_id",
                "identity_id",
                "persona_id",
                "conversation_id",
            ],
            [
                "characters.scenes.id",
                "characters.scenes.continuity_id",
                "characters.scenes.identity_id",
                "characters.scenes.persona_id",
                "characters.scenes.conversation_id",
            ],
            name="fk_memory_effect_scene",
        ),
        ForeignKeyConstraint(
            ["source_persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_memory_effect_source_message",
        ),
        CheckConstraint("mode = 'storyline'", name="ck_memory_effect_mode"),
        CheckConstraint(
            "state IN ('reserved', 'no_change', 'applied')",
            name="ck_memory_effect_state",
        ),
        CheckConstraint(
            "(state = 'reserved' AND provenance IS NULL AND selection_id IS NULL AND completed_at IS NULL) OR (state <> 'reserved' AND provenance IS NOT NULL AND selection_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_memory_effect_terminal",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
        doc="Stable extraction-effect identifier.",
    )
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning Storyline.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Source scene conversation."
    )
    mode: Mapped[str] = mapped_column(
        String(16), default="storyline", doc="Fixed Storyline mode discriminator."
    )
    scene_id: Mapped[UUID] = mapped_column(Uuid, doc="Source scene identifier.")
    source_persona_message_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Unique complete persona-message checkpoint."
    )
    state: Mapped[str] = mapped_column(String(16), doc="Extraction effect state.")
    selection_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Terminal selection snapshot identifier."
    )
    provenance: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, doc="Terminal selector extractor prompt and model provenance."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC reservation time."
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), doc="UTC terminal transition time."
    )


class MemoryConflictModel(CharactersBase):
    """Persist an unresolved or dismissed extraction contradiction."""

    __tablename__ = "memory_conflicts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.storylines.continuity_id",
                "characters.storylines.identity_id",
                "characters.storylines.persona_id",
            ],
            name="fk_memory_conflict_owner",
        ),
        ForeignKeyConstraint(
            ["memory_id", "continuity_id"],
            [
                "characters.storyline_memories.id",
                "characters.storyline_memories.continuity_id",
            ],
            name="fk_memory_conflict_memory",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["observed_revision_id", "memory_id", "continuity_id"],
            [
                "characters.memory_revisions.id",
                "characters.memory_revisions.memory_id",
                "characters.memory_revisions.continuity_id",
            ],
            name="fk_memory_conflict_observed_revision",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "continuity_id"],
            [
                "characters.memory_evidence.id",
                "characters.memory_evidence.continuity_id",
            ],
            name="fk_memory_conflict_evidence",
        ),
        ForeignKeyConstraint(
            ["effect_id"],
            ["characters.memory_extraction_effects.id"],
            name="fk_memory_conflict_effect",
        ),
        CheckConstraint(
            "(memory_id IS NULL AND observed_revision_id IS NULL) OR (memory_id IS NOT NULL AND observed_revision_id IS NOT NULL)",
            name="ck_memory_conflict_target",
        ),
        CheckConstraint(
            "state IN ('unresolved', 'dismissed')", name="ck_memory_conflict_state"
        ),
        CheckConstraint(
            "(state = 'unresolved' AND dismissed_at IS NULL) OR (state = 'dismissed' AND dismissed_at IS NOT NULL)",
            name="ck_memory_conflict_dismissal",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable conflict identifier."
    )
    continuity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning Storyline.")
    identity_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning identity.")
    persona_id: Mapped[UUID] = mapped_column(Uuid, doc="Owning persona.")
    memory_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Target logical memory when known."
    )
    observed_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, doc="Target revision observed during validation."
    )
    evidence_id: Mapped[UUID] = mapped_column(
        Uuid, unique=True, doc="Exact conflicting source evidence."
    )
    effect_id: Mapped[UUID] = mapped_column(
        Uuid, doc="Atomic extraction effect that recorded the conflict."
    )
    proposed_subject: Mapped[str] = mapped_column(
        String(256), doc="Proposed normalized subject."
    )
    proposed_content: Mapped[str] = mapped_column(
        String(4096), doc="Proposed conflicting assertion."
    )
    state: Mapped[str] = mapped_column(String(16), doc="Conflict lifecycle state.")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), doc="UTC conflict creation time."
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), doc="UTC dismissal time when dismissed."
    )
