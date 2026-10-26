"""Persist Storyline memory lineages and extraction records.

Revision ID: b17c4e92a6d1
Revises: e42b7c91d5a0
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b17c4e92a6d1"
down_revision: str | Sequence[str] | None = "e42b7c91d5a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add owned memory, evidence, revision, effect, and conflict records."""

    op.create_unique_constraint(
        "uq_scene_ownership",
        "scenes",
        ["id", "continuity_id", "identity_id", "persona_id"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_scene_complete_ownership",
        "scenes",
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        schema="characters",
    )

    op.create_table(
        "storyline_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("subject_key", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "continuity_id", name="uq_storyline_memory_ownership"
        ),
        sa.UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_storyline_memory_complete_ownership",
        ),
        sa.UniqueConstraint(
            "continuity_id", "subject_key", name="uq_storyline_memory_subject"
        ),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.storylines.continuity_id",
                "characters.storylines.identity_id",
                "characters.storylines.persona_id",
            ],
            name="fk_storyline_memory_owner",
        ),
        schema="characters",
    )
    op.create_table(
        "memory_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("source_persona_message_id", sa.Uuid(), nullable=False),
        sa.Column("persona_checkpoint", sa.Integer(), nullable=False),
        sa.Column("occurrence_scene_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_position", sa.Integer(), nullable=False),
        sa.Column("learned_scene_id", sa.Uuid(), nullable=False),
        sa.Column("learned_position", sa.Integer(), nullable=False),
        sa.Column("extraction", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "continuity_id", name="uq_memory_evidence_owner"),
        sa.UniqueConstraint(
            "id",
            "memory_id",
            "continuity_id",
            name="uq_memory_evidence_lineage_owner",
        ),
        sa.UniqueConstraint(
            "memory_id",
            "source_persona_message_id",
            name="uq_memory_evidence_source_turn",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_memory_evidence_user_message",
        ),
        sa.ForeignKeyConstraint(
            ["source_persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_memory_evidence_persona_message",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_scene_id", "continuity_id", "identity_id", "persona_id"],
            [
                "characters.scenes.id",
                "characters.scenes.continuity_id",
                "characters.scenes.identity_id",
                "characters.scenes.persona_id",
            ],
            name="fk_memory_evidence_occurrence_scene",
        ),
        sa.CheckConstraint("mode = 'storyline'", name="ck_memory_evidence_mode"),
        sa.CheckConstraint(
            "purpose IN ('support', 'conflict')",
            name="ck_memory_evidence_purpose",
        ),
        sa.CheckConstraint(
            "persona_checkpoint > 0 AND persona_checkpoint % 2 = 0",
            name="ck_memory_evidence_checkpoint",
        ),
        sa.CheckConstraint(
            "occurrence_position > 0 AND learned_position > 0 AND occurrence_position <= learned_position",
            name="ck_memory_evidence_temporal_positions",
        ),
        sa.CheckConstraint(
            "learned_scene_id = scene_id",
            name="ck_memory_evidence_learned_scene",
        ),
        schema="characters",
    )
    op.create_table(
        "memory_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("content", sa.String(4096), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("authorship", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source_evidence_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "memory_id", "continuity_id", name="uq_memory_revision_owner"
        ),
        sa.UniqueConstraint(
            "memory_id", "revision", name="uq_memory_revision_position"
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "continuity_id"],
            [
                "characters.storyline_memories.id",
                "characters.storyline_memories.continuity_id",
            ],
            name="fk_memory_revision_memory",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id", "memory_id", "continuity_id"],
            [
                "characters.memory_revisions.id",
                "characters.memory_revisions.memory_id",
                "characters.memory_revisions.continuity_id",
            ],
            name="fk_memory_revision_predecessor",
        ),
        sa.ForeignKeyConstraint(
            ["source_evidence_id", "memory_id", "continuity_id"],
            [
                "characters.memory_evidence.id",
                "characters.memory_evidence.memory_id",
                "characters.memory_evidence.continuity_id",
            ],
            name="fk_memory_revision_source",
        ),
        sa.CheckConstraint("revision > 0", name="ck_memory_revision_position"),
        sa.CheckConstraint(
            "state IN ('active', 'excluded', 'superseded')",
            name="ck_memory_revision_state",
        ),
        sa.CheckConstraint(
            "authorship IN ('extracted', 'user')",
            name="ck_memory_revision_authorship",
        ),
        sa.CheckConstraint(
            "kind IN ('extraction', 'automatic_supersede', 'user_correction', 'exclusion', 'reactivation')",
            name="ck_memory_revision_kind",
        ),
        sa.CheckConstraint(
            "(revision = 1 AND predecessor_id IS NULL AND kind = 'extraction' AND authorship = 'extracted') OR (revision > 1 AND predecessor_id IS NOT NULL AND kind <> 'extraction')",
            name="ck_memory_revision_origin",
        ),
        schema="characters",
    )
    op.create_foreign_key(
        "fk_storyline_memory_current_revision",
        "storyline_memories",
        "memory_revisions",
        ["current_revision_id", "id", "continuity_id"],
        ["id", "memory_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
        use_alter=True,
    )
    op.create_index(
        "uq_memory_current_revision",
        "memory_revisions",
        ["memory_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("state IN ('active', 'excluded')"),
        sqlite_where=sa.text("state IN ('active', 'excluded')"),
    )
    op.create_table(
        "memory_extraction_effects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=False),
        sa.Column("source_persona_message_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("selection_id", sa.Uuid(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_persona_message_id", name="uq_memory_effect_source_message"
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["source_persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_memory_effect_source_message",
        ),
        sa.CheckConstraint("mode = 'storyline'", name="ck_memory_effect_mode"),
        sa.CheckConstraint(
            "state IN ('reserved', 'no_change', 'applied')",
            name="ck_memory_effect_state",
        ),
        sa.CheckConstraint(
            "(state = 'reserved' AND provenance IS NULL AND selection_id IS NULL AND completed_at IS NULL) OR (state <> 'reserved' AND provenance IS NOT NULL AND selection_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_memory_effect_terminal",
        ),
        schema="characters",
    )
    op.create_table(
        "memory_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column("observed_revision_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_subject", sa.String(256), nullable=False),
        sa.Column("proposed_content", sa.String(4096), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.storylines.continuity_id",
                "characters.storylines.identity_id",
                "characters.storylines.persona_id",
            ],
            name="fk_memory_conflict_owner",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "continuity_id"],
            [
                "characters.storyline_memories.id",
                "characters.storyline_memories.continuity_id",
            ],
            name="fk_memory_conflict_memory",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observed_revision_id", "memory_id", "continuity_id"],
            [
                "characters.memory_revisions.id",
                "characters.memory_revisions.memory_id",
                "characters.memory_revisions.continuity_id",
            ],
            name="fk_memory_conflict_observed_revision",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "continuity_id"],
            [
                "characters.memory_evidence.id",
                "characters.memory_evidence.continuity_id",
            ],
            name="fk_memory_conflict_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["effect_id"],
            ["characters.memory_extraction_effects.id"],
            name="fk_memory_conflict_effect",
        ),
        sa.CheckConstraint(
            "(memory_id IS NULL AND observed_revision_id IS NULL) OR (memory_id IS NOT NULL AND observed_revision_id IS NOT NULL)",
            name="ck_memory_conflict_target",
        ),
        sa.CheckConstraint(
            "state IN ('unresolved', 'dismissed')", name="ck_memory_conflict_state"
        ),
        sa.CheckConstraint(
            "(state = 'unresolved' AND dismissed_at IS NULL) OR (state = 'dismissed' AND dismissed_at IS NOT NULL)",
            name="ck_memory_conflict_dismissal",
        ),
        schema="characters",
    )


def downgrade() -> None:
    """Remove all Storyline memory persistence objects."""

    op.drop_table("memory_conflicts", schema="characters")
    op.drop_table("memory_extraction_effects", schema="characters")
    op.drop_constraint(
        "fk_storyline_memory_current_revision",
        "storyline_memories",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_table("memory_revisions", schema="characters")
    op.drop_table("memory_evidence", schema="characters")
    op.drop_table("storyline_memories", schema="characters")
    op.drop_constraint(
        "uq_scene_complete_ownership", "scenes", schema="characters", type_="unique"
    )
    op.drop_constraint(
        "uq_scene_ownership", "scenes", schema="characters", type_="unique"
    )
