"""Add Timeline ownership and day provenance to Characters memory.

Revision ID: d6e8f1a2b3c4
Revises: 9c4e7a1b2d30
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d6e8f1a2b3c4"
down_revision: str | Sequence[str] | None = "9c4e7a1b2d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Generalize Storyline memory rows for Timeline day provenance."""

    op.create_unique_constraint(
        "uq_timeline_day_complete_ownership",
        "timeline_days",
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        schema="characters",
    )

    op.add_column(
        "storyline_memories",
        sa.Column(
            "mode",
            sa.String(length=16),
            server_default="storyline",
            nullable=False,
        ),
        schema="characters",
    )
    op.drop_constraint(
        "fk_storyline_memory_owner",
        "storyline_memories",
        schema="characters",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_storyline_memory_owner",
        "storyline_memories",
        "continuities",
        ["continuity_id", "identity_id", "persona_id", "mode"],
        ["id", "identity_id", "persona_id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_check_constraint(
        "ck_storyline_memory_mode",
        "storyline_memories",
        "mode IN ('storyline', 'timeline')",
        schema="characters",
    )

    op.alter_column(
        "memory_evidence", "scene_id", nullable=True, schema="characters"
    )
    op.alter_column(
        "memory_evidence",
        "occurrence_scene_id",
        nullable=True,
        schema="characters",
    )
    op.alter_column(
        "memory_evidence",
        "learned_scene_id",
        nullable=True,
        schema="characters",
    )
    for column in ("day_id", "occurrence_day_id", "learned_day_id"):
        op.add_column(
            "memory_evidence",
            sa.Column(column, sa.Uuid(), nullable=True),
            schema="characters",
        )
    op.drop_constraint(
        "ck_memory_evidence_mode",
        "memory_evidence",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "ck_memory_evidence_learned_scene",
        "memory_evidence",
        schema="characters",
        type_="check",
    )
    op.create_foreign_key(
        "fk_memory_evidence_day",
        "memory_evidence",
        "timeline_days",
        ["day_id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_foreign_key(
        "fk_memory_evidence_occurrence_day",
        "memory_evidence",
        "timeline_days",
        ["occurrence_day_id", "continuity_id", "identity_id", "persona_id"],
        ["id", "continuity_id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_check_constraint(
        "ck_memory_evidence_mode",
        "memory_evidence",
        "mode IN ('storyline', 'timeline')",
        schema="characters",
    )
    op.create_check_constraint(
        "ck_memory_evidence_temporal_owner",
        "memory_evidence",
        "(mode = 'storyline' AND scene_id IS NOT NULL AND day_id IS NULL AND occurrence_scene_id IS NOT NULL AND occurrence_day_id IS NULL AND learned_scene_id IS NOT NULL AND learned_day_id IS NULL) OR "
        "(mode = 'timeline' AND scene_id IS NULL AND day_id IS NOT NULL AND occurrence_scene_id IS NULL AND occurrence_day_id IS NOT NULL AND learned_scene_id IS NULL AND learned_day_id IS NOT NULL)",
        schema="characters",
    )
    op.create_check_constraint(
        "ck_memory_evidence_learned_owner",
        "memory_evidence",
        "(mode = 'storyline' AND learned_scene_id = scene_id) OR (mode = 'timeline' AND learned_day_id = day_id)",
        schema="characters",
    )

    op.alter_column(
        "memory_extraction_effects", "scene_id", nullable=True, schema="characters"
    )
    op.add_column(
        "memory_extraction_effects",
        sa.Column("day_id", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.drop_constraint(
        "ck_memory_effect_mode",
        "memory_extraction_effects",
        schema="characters",
        type_="check",
    )
    op.create_foreign_key(
        "fk_memory_effect_day",
        "memory_extraction_effects",
        "timeline_days",
        ["day_id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_check_constraint(
        "ck_memory_effect_mode",
        "memory_extraction_effects",
        "mode IN ('storyline', 'timeline')",
        schema="characters",
    )
    op.create_check_constraint(
        "ck_memory_effect_temporal_owner",
        "memory_extraction_effects",
        "(mode = 'storyline' AND scene_id IS NOT NULL AND day_id IS NULL) OR (mode = 'timeline' AND scene_id IS NULL AND day_id IS NOT NULL)",
        schema="characters",
    )

    op.drop_constraint(
        "fk_memory_conflict_owner",
        "memory_conflicts",
        schema="characters",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_memory_conflict_owner",
        "memory_conflicts",
        "continuities",
        ["continuity_id", "identity_id", "persona_id"],
        ["id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )


def downgrade() -> None:
    """Remove Timeline memory after discarding Timeline-owned lineages."""

    op.execute(
        "DELETE FROM characters.memory_conflicts WHERE effect_id IN "
        "(SELECT id FROM characters.memory_extraction_effects WHERE mode = 'timeline')"
    )
    op.execute(
        "DELETE FROM characters.memory_extraction_effects WHERE mode = 'timeline'"
    )
    op.execute(
        "UPDATE characters.storyline_memories SET current_revision_id = NULL "
        "WHERE mode = 'timeline'"
    )
    op.execute("DELETE FROM characters.storyline_memories WHERE mode = 'timeline'")

    op.drop_constraint(
        "fk_memory_conflict_owner",
        "memory_conflicts",
        schema="characters",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_memory_conflict_owner",
        "memory_conflicts",
        "storylines",
        ["continuity_id", "identity_id", "persona_id"],
        ["continuity_id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )

    op.drop_constraint(
        "ck_memory_effect_temporal_owner",
        "memory_extraction_effects",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "ck_memory_effect_mode",
        "memory_extraction_effects",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "fk_memory_effect_day",
        "memory_extraction_effects",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_column("memory_extraction_effects", "day_id", schema="characters")
    op.alter_column(
        "memory_extraction_effects", "scene_id", nullable=False, schema="characters"
    )
    op.create_check_constraint(
        "ck_memory_effect_mode",
        "memory_extraction_effects",
        "mode = 'storyline'",
        schema="characters",
    )

    op.drop_constraint(
        "ck_memory_evidence_learned_owner",
        "memory_evidence",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "ck_memory_evidence_temporal_owner",
        "memory_evidence",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "ck_memory_evidence_mode",
        "memory_evidence",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "fk_memory_evidence_occurrence_day",
        "memory_evidence",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_memory_evidence_day",
        "memory_evidence",
        schema="characters",
        type_="foreignkey",
    )
    for column in ("learned_day_id", "occurrence_day_id", "day_id"):
        op.drop_column("memory_evidence", column, schema="characters")
    op.alter_column(
        "memory_evidence", "learned_scene_id", nullable=False, schema="characters"
    )
    op.alter_column(
        "memory_evidence", "occurrence_scene_id", nullable=False, schema="characters"
    )
    op.alter_column(
        "memory_evidence", "scene_id", nullable=False, schema="characters"
    )
    op.create_check_constraint(
        "ck_memory_evidence_mode",
        "memory_evidence",
        "mode = 'storyline'",
        schema="characters",
    )
    op.create_check_constraint(
        "ck_memory_evidence_learned_scene",
        "memory_evidence",
        "learned_scene_id = scene_id",
        schema="characters",
    )

    op.drop_constraint(
        "ck_storyline_memory_mode",
        "storyline_memories",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "fk_storyline_memory_owner",
        "storyline_memories",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_column("storyline_memories", "mode", schema="characters")
    op.create_foreign_key(
        "fk_storyline_memory_owner",
        "storyline_memories",
        "storylines",
        ["continuity_id", "identity_id", "persona_id"],
        ["continuity_id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.drop_constraint(
        "uq_timeline_day_complete_ownership",
        "timeline_days",
        schema="characters",
        type_="unique",
    )
