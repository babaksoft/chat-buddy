"""Unify continuity memory around Entry provenance.

Revision ID: 4b8e2d7c1a90
Revises: f3a7c9e1b2d4
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "4b8e2d7c1a90"
down_revision: str | Sequence[str] | None = "f3a7c9e1b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename continuity memory and normalize all provenance to Entries."""

    op.rename_table(
        "storyline_memories", "continuity_memories", schema="characters"
    )
    for old, new in (
        ("uq_storyline_memory_ownership", "uq_continuity_memory_ownership"),
        (
            "uq_storyline_memory_complete_ownership",
            "uq_continuity_memory_complete_ownership",
        ),
        ("uq_storyline_memory_subject", "uq_continuity_memory_subject"),
        ("fk_storyline_memory_owner", "fk_continuity_memory_owner"),
        ("ck_storyline_memory_mode", "ck_continuity_memory_mode"),
        (
            "fk_storyline_memory_current_revision",
            "fk_continuity_memory_current_revision",
        ),
    ):
        op.execute(
            f"ALTER TABLE characters.continuity_memories RENAME CONSTRAINT {old} TO {new}"
        )

    _normalize_evidence()
    _normalize_effects()


def downgrade() -> None:
    """Restore the prior mode-specific Scene and Timeline Day columns."""

    _restore_effects()
    _restore_evidence()

    for old, new in (
        ("uq_continuity_memory_ownership", "uq_storyline_memory_ownership"),
        (
            "uq_continuity_memory_complete_ownership",
            "uq_storyline_memory_complete_ownership",
        ),
        ("uq_continuity_memory_subject", "uq_storyline_memory_subject"),
        ("fk_continuity_memory_owner", "fk_storyline_memory_owner"),
        ("ck_continuity_memory_mode", "ck_storyline_memory_mode"),
        (
            "fk_continuity_memory_current_revision",
            "fk_storyline_memory_current_revision",
        ),
    ):
        op.execute(
            f"ALTER TABLE characters.continuity_memories RENAME CONSTRAINT {old} TO {new}"
        )
    op.rename_table(
        "continuity_memories", "storyline_memories", schema="characters"
    )


def _normalize_evidence() -> None:
    """Replace paired evidence provenance with required Entry identifiers."""

    for name in (
        "fk_memory_evidence_scene",
        "fk_memory_evidence_day",
        "fk_memory_evidence_occurrence_scene",
        "fk_memory_evidence_occurrence_day",
    ):
        op.drop_constraint(
            name, "memory_evidence", schema="characters", type_="foreignkey"
        )
    for name in (
        "ck_memory_evidence_temporal_owner",
        "ck_memory_evidence_learned_owner",
    ):
        op.drop_constraint(name, "memory_evidence", schema="characters", type_="check")

    for column in ("entry_id", "occurrence_entry_id", "learned_entry_id"):
        op.add_column(
            "memory_evidence",
            sa.Column(column, sa.Uuid(), nullable=True),
            schema="characters",
        )
    op.execute(
        "UPDATE characters.memory_evidence SET "
        "entry_id = COALESCE(scene_id, day_id), "
        "occurrence_entry_id = COALESCE(occurrence_scene_id, occurrence_day_id), "
        "learned_entry_id = COALESCE(learned_scene_id, learned_day_id)"
    )
    for column in ("entry_id", "occurrence_entry_id", "learned_entry_id"):
        op.alter_column(
            "memory_evidence", column, nullable=False, schema="characters"
        )
    for column in (
        "scene_id",
        "day_id",
        "occurrence_scene_id",
        "occurrence_day_id",
        "learned_scene_id",
        "learned_day_id",
    ):
        op.drop_column("memory_evidence", column, schema="characters")

    _create_evidence_entry_constraints()


def _normalize_effects() -> None:
    """Replace paired extraction-effect provenance with one required Entry."""

    for name in ("fk_memory_effect_scene", "fk_memory_effect_day"):
        op.drop_constraint(
            name,
            "memory_extraction_effects",
            schema="characters",
            type_="foreignkey",
        )
    op.drop_constraint(
        "ck_memory_effect_temporal_owner",
        "memory_extraction_effects",
        schema="characters",
        type_="check",
    )
    op.add_column(
        "memory_extraction_effects",
        sa.Column("entry_id", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.execute(
        "UPDATE characters.memory_extraction_effects "
        "SET entry_id = COALESCE(scene_id, day_id)"
    )
    op.alter_column(
        "memory_extraction_effects", "entry_id", nullable=False, schema="characters"
    )
    op.drop_column("memory_extraction_effects", "scene_id", schema="characters")
    op.drop_column("memory_extraction_effects", "day_id", schema="characters")
    _create_effect_entry_constraints()


def _restore_evidence() -> None:
    """Restore paired subtype evidence columns for downgrade."""

    for name in (
        "fk_memory_evidence_entry",
        "fk_memory_evidence_entry_mode",
        "fk_memory_evidence_occurrence_entry",
        "fk_memory_evidence_occurrence_mode",
        "fk_memory_evidence_learned_entry",
        "fk_memory_evidence_learned_mode",
    ):
        op.drop_constraint(
            name, "memory_evidence", schema="characters", type_="foreignkey"
        )
    op.drop_constraint(
        "ck_memory_evidence_learned_owner",
        "memory_evidence",
        schema="characters",
        type_="check",
    )
    for column in (
        "scene_id",
        "day_id",
        "occurrence_scene_id",
        "occurrence_day_id",
        "learned_scene_id",
        "learned_day_id",
    ):
        op.add_column(
            "memory_evidence",
            sa.Column(column, sa.Uuid(), nullable=True),
            schema="characters",
        )
    op.execute(
        "UPDATE characters.memory_evidence SET "
        "scene_id = CASE WHEN mode = 'storyline' THEN entry_id END, "
        "day_id = CASE WHEN mode = 'timeline' THEN entry_id END, "
        "occurrence_scene_id = CASE WHEN mode = 'storyline' THEN occurrence_entry_id END, "
        "occurrence_day_id = CASE WHEN mode = 'timeline' THEN occurrence_entry_id END, "
        "learned_scene_id = CASE WHEN mode = 'storyline' THEN learned_entry_id END, "
        "learned_day_id = CASE WHEN mode = 'timeline' THEN learned_entry_id END"
    )
    for column in ("entry_id", "occurrence_entry_id", "learned_entry_id"):
        op.drop_column("memory_evidence", column, schema="characters")
    _create_legacy_evidence_constraints()


def _restore_effects() -> None:
    """Restore paired subtype extraction-effect columns for downgrade."""

    for name in ("fk_memory_effect_entry", "fk_memory_effect_entry_mode"):
        op.drop_constraint(
            name,
            "memory_extraction_effects",
            schema="characters",
            type_="foreignkey",
        )
    for column in ("scene_id", "day_id"):
        op.add_column(
            "memory_extraction_effects",
            sa.Column(column, sa.Uuid(), nullable=True),
            schema="characters",
        )
    op.execute(
        "UPDATE characters.memory_extraction_effects SET "
        "scene_id = CASE WHEN mode = 'storyline' THEN entry_id END, "
        "day_id = CASE WHEN mode = 'timeline' THEN entry_id END"
    )
    op.drop_column("memory_extraction_effects", "entry_id", schema="characters")
    _create_legacy_effect_constraints()


def _create_evidence_entry_constraints() -> None:
    """Create complete Entry ownership constraints for evidence."""

    op.create_foreign_key(
        "fk_memory_evidence_entry",
        "memory_evidence",
        "continuity_entries",
        ["entry_id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    for name, column in (
        ("fk_memory_evidence_entry_mode", "entry_id"),
        ("fk_memory_evidence_occurrence_mode", "occurrence_entry_id"),
        ("fk_memory_evidence_learned_mode", "learned_entry_id"),
    ):
        op.create_foreign_key(
            name,
            "memory_evidence",
            "continuity_entries",
            [column, "mode"],
            ["id", "mode"],
            source_schema="characters",
            referent_schema="characters",
        )
    for name, column in (
        ("fk_memory_evidence_occurrence_entry", "occurrence_entry_id"),
        ("fk_memory_evidence_learned_entry", "learned_entry_id"),
    ):
        op.create_foreign_key(
            name,
            "memory_evidence",
            "continuity_entries",
            [column, "continuity_id", "identity_id", "persona_id"],
            ["id", "continuity_id", "identity_id", "persona_id"],
            source_schema="characters",
            referent_schema="characters",
        )
    op.create_check_constraint(
        "ck_memory_evidence_learned_owner",
        "memory_evidence",
        "learned_entry_id = entry_id",
        schema="characters",
    )


def _create_effect_entry_constraints() -> None:
    """Create complete Entry ownership constraints for extraction effects."""

    op.create_foreign_key(
        "fk_memory_effect_entry",
        "memory_extraction_effects",
        "continuity_entries",
        ["entry_id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_foreign_key(
        "fk_memory_effect_entry_mode",
        "memory_extraction_effects",
        "continuity_entries",
        ["entry_id", "mode"],
        ["id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )


def _create_legacy_evidence_constraints() -> None:
    """Recreate the Slice 3 evidence constraints."""

    for name, column in (
        ("fk_memory_evidence_scene", "scene_id"),
        ("fk_memory_evidence_day", "day_id"),
    ):
        op.create_foreign_key(
            name,
            "memory_evidence",
            "continuity_entries",
            [column, "continuity_id", "identity_id", "persona_id", "conversation_id"],
            ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
            source_schema="characters",
            referent_schema="characters",
        )
    for name, column in (
        ("fk_memory_evidence_occurrence_scene", "occurrence_scene_id"),
        ("fk_memory_evidence_occurrence_day", "occurrence_day_id"),
    ):
        op.create_foreign_key(
            name,
            "memory_evidence",
            "continuity_entries",
            [column, "continuity_id", "identity_id", "persona_id"],
            ["id", "continuity_id", "identity_id", "persona_id"],
            source_schema="characters",
            referent_schema="characters",
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
        "(mode = 'storyline' AND learned_scene_id = scene_id) OR "
        "(mode = 'timeline' AND learned_day_id = day_id)",
        schema="characters",
    )


def _create_legacy_effect_constraints() -> None:
    """Recreate the Slice 3 extraction-effect constraints."""

    for name, column in (
        ("fk_memory_effect_scene", "scene_id"),
        ("fk_memory_effect_day", "day_id"),
    ):
        op.create_foreign_key(
            name,
            "memory_extraction_effects",
            "continuity_entries",
            [column, "continuity_id", "identity_id", "persona_id", "conversation_id"],
            ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
            source_schema="characters",
            referent_schema="characters",
        )
    op.create_check_constraint(
        "ck_memory_effect_temporal_owner",
        "memory_extraction_effects",
        "(mode = 'storyline' AND scene_id IS NOT NULL AND day_id IS NULL) OR "
        "(mode = 'timeline' AND scene_id IS NULL AND day_id IS NOT NULL)",
        schema="characters",
    )
