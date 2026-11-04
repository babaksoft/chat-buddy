"""Normalize Scene and Timeline Day persistence around Entries.

Revision ID: f3a7c9e1b2d4
Revises: d6e8f1a2b3c4
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "f3a7c9e1b2d4"
down_revision: str | Sequence[str] | None = "d6e8f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MEMORY_FOREIGN_KEYS = (
    ("memory_evidence", "fk_memory_evidence_scene"),
    ("memory_evidence", "fk_memory_evidence_day"),
    ("memory_evidence", "fk_memory_evidence_occurrence_scene"),
    ("memory_evidence", "fk_memory_evidence_occurrence_day"),
    ("memory_extraction_effects", "fk_memory_effect_scene"),
    ("memory_extraction_effects", "fk_memory_effect_day"),
)


def upgrade() -> None:
    """Create Entry parents and reduce Scene and Day rows to details."""

    op.create_table(
        "continuity_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "mode IN ('storyline', 'timeline')", name="ck_continuity_entry_mode"
        ),
        sa.CheckConstraint("position >= 1", name="ck_continuity_entry_position"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id", "mode"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
                "characters.continuities.mode",
            ],
            name="fk_continuity_entry_continuity",
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
            name="fk_continuity_entry_conversation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "mode", name="uq_continuity_entry_mode"),
        sa.UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_continuity_entry_ownership",
        ),
        sa.UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            "conversation_id",
            name="uq_continuity_entry_complete_ownership",
        ),
        sa.UniqueConstraint(
            "continuity_id", "position", name="uq_continuity_entry_position"
        ),
        sa.UniqueConstraint("conversation_id", name="uq_continuity_entry_conversation"),
        schema="characters",
    )
    op.execute(
        "INSERT INTO characters.continuity_entries "
        "(id, continuity_id, identity_id, persona_id, conversation_id, mode, position) "
        "SELECT id, continuity_id, identity_id, persona_id, conversation_id, mode, position "
        "FROM characters.scenes"
    )
    op.execute(
        "INSERT INTO characters.continuity_entries "
        "(id, continuity_id, identity_id, persona_id, conversation_id, mode, position) "
        "SELECT id, continuity_id, identity_id, persona_id, conversation_id, mode, position "
        "FROM characters.timeline_days"
    )

    for table, constraint in _MEMORY_FOREIGN_KEYS:
        op.drop_constraint(constraint, table, schema="characters", type_="foreignkey")

    _normalize_scenes()
    _normalize_timeline_days()
    _point_memory_at_entries()


def downgrade() -> None:
    """Restore duplicated subtype ownership columns from exact Entries."""

    for table, constraint in _MEMORY_FOREIGN_KEYS:
        op.drop_constraint(constraint, table, schema="characters", type_="foreignkey")

    _restore_scenes()
    _restore_timeline_days()
    _point_memory_at_subtypes()
    op.drop_table("continuity_entries", schema="characters")


def _normalize_scenes() -> None:
    """Reduce Scene rows to their Storyline-specific details."""

    op.add_column(
        "scenes",
        sa.Column(
            "entry_mode",
            sa.String(length=16),
            server_default="storyline",
            nullable=False,
        ),
        schema="characters",
    )
    for constraint, type_ in (
        ("fk_scene_storyline_ownership", "foreignkey"),
        ("fk_scene_conversation_ownership", "foreignkey"),
        ("uq_scene_ownership", "unique"),
        ("uq_scene_complete_ownership", "unique"),
        ("uq_scene_storyline_position", "unique"),
        ("uq_scene_conversation", "unique"),
        ("ck_scene_mode", "check"),
        ("ck_scene_position", "check"),
    ):
        op.drop_constraint(constraint, "scenes", schema="characters", type_=type_)
    for column in (
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
        "mode",
        "position",
    ):
        op.drop_column("scenes", column, schema="characters")
    op.create_unique_constraint(
        "uq_scene_entry_mode", "scenes", ["id", "entry_mode"], schema="characters"
    )
    op.create_check_constraint(
        "ck_scene_mode", "scenes", "entry_mode = 'storyline'", schema="characters"
    )
    op.create_foreign_key(
        "fk_scene_entry",
        "scenes",
        "continuity_entries",
        ["id", "entry_mode"],
        ["id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )


def _normalize_timeline_days() -> None:
    """Reduce Timeline Day rows to their calendar and closure details."""

    op.drop_constraint(
        "fk_timeline_day_settled_leaf",
        "timeline_days",
        schema="characters",
        type_="foreignkey",
    )
    op.add_column(
        "timeline_days",
        sa.Column(
            "entry_mode",
            sa.String(length=16),
            server_default="timeline",
            nullable=False,
        ),
        schema="characters",
    )
    for constraint, type_ in (
        ("fk_timeline_day_owner", "foreignkey"),
        ("fk_timeline_day_conversation", "foreignkey"),
        ("uq_timeline_day_ownership", "unique"),
        ("uq_timeline_day_complete_ownership", "unique"),
        ("uq_timeline_day_position", "unique"),
        ("uq_timeline_day_date", "unique"),
        ("uq_timeline_day_conversation", "unique"),
        ("ck_timeline_day_mode", "check"),
        ("ck_timeline_day_position", "check"),
    ):
        op.drop_constraint(
            constraint, "timeline_days", schema="characters", type_=type_
        )
    for column in (
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
        "mode",
        "position",
    ):
        op.drop_column("timeline_days", column, schema="characters")
    op.create_unique_constraint(
        "uq_timeline_day_entry_mode",
        "timeline_days",
        ["id", "entry_mode"],
        schema="characters",
    )
    op.create_check_constraint(
        "ck_timeline_day_mode",
        "timeline_days",
        "entry_mode = 'timeline'",
        schema="characters",
    )
    op.create_foreign_key(
        "fk_timeline_day_entry",
        "timeline_days",
        "continuity_entries",
        ["id", "entry_mode"],
        ["id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_foreign_key(
        "fk_timeline_day_settled_leaf",
        "timeline_days",
        "messages",
        ["settled_selected_leaf_id"],
        ["id"],
        source_schema="characters",
        referent_schema="characters",
    )


def _point_memory_at_entries() -> None:
    """Preserve transitional memory columns against normalized Entries."""

    _create_memory_foreign_keys("continuity_entries")


def _restore_scenes() -> None:
    """Restore the prior denormalized Scene relation."""

    op.drop_constraint(
        "fk_scene_entry", "scenes", schema="characters", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_scene_entry_mode", "scenes", schema="characters", type_="unique"
    )
    op.drop_constraint("ck_scene_mode", "scenes", schema="characters", type_="check")
    _add_shared_columns("scenes")
    op.execute(
        "UPDATE characters.scenes AS subtype SET "
        "continuity_id = entry.continuity_id, identity_id = entry.identity_id, "
        "persona_id = entry.persona_id, conversation_id = entry.conversation_id, "
        "mode = entry.mode, position = entry.position "
        "FROM characters.continuity_entries AS entry WHERE subtype.id = entry.id"
    )
    _require_shared_columns("scenes")
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
    op.create_unique_constraint(
        "uq_scene_storyline_position",
        "scenes",
        ["continuity_id", "position"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_scene_conversation", "scenes", ["conversation_id"], schema="characters"
    )
    op.create_check_constraint(
        "ck_scene_mode", "scenes", "mode = 'storyline'", schema="characters"
    )
    op.create_check_constraint(
        "ck_scene_position", "scenes", "position >= 1", schema="characters"
    )
    op.create_foreign_key(
        "fk_scene_storyline_ownership",
        "scenes",
        "storylines",
        ["continuity_id", "identity_id", "persona_id"],
        ["continuity_id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_foreign_key(
        "fk_scene_conversation_ownership",
        "scenes",
        "conversations",
        ["conversation_id", "continuity_id", "identity_id", "persona_id", "mode"],
        ["id", "continuity_id", "identity_id", "persona_id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.drop_column("scenes", "entry_mode", schema="characters")


def _restore_timeline_days() -> None:
    """Restore the prior denormalized Timeline Day relation."""

    op.drop_constraint(
        "fk_timeline_day_settled_leaf",
        "timeline_days",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_timeline_day_entry",
        "timeline_days",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_timeline_day_entry_mode",
        "timeline_days",
        schema="characters",
        type_="unique",
    )
    op.drop_constraint(
        "ck_timeline_day_mode",
        "timeline_days",
        schema="characters",
        type_="check",
    )
    _add_shared_columns("timeline_days")
    op.execute(
        "UPDATE characters.timeline_days AS subtype SET "
        "continuity_id = entry.continuity_id, identity_id = entry.identity_id, "
        "persona_id = entry.persona_id, conversation_id = entry.conversation_id, "
        "mode = entry.mode, position = entry.position "
        "FROM characters.continuity_entries AS entry WHERE subtype.id = entry.id"
    )
    _require_shared_columns("timeline_days")
    op.create_unique_constraint(
        "uq_timeline_day_ownership",
        "timeline_days",
        ["id", "continuity_id", "identity_id", "persona_id"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_timeline_day_complete_ownership",
        "timeline_days",
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_timeline_day_position",
        "timeline_days",
        ["continuity_id", "position"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_timeline_day_date",
        "timeline_days",
        ["continuity_id", "local_date"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_timeline_day_conversation",
        "timeline_days",
        ["conversation_id"],
        schema="characters",
    )
    op.create_check_constraint(
        "ck_timeline_day_mode",
        "timeline_days",
        "mode = 'timeline'",
        schema="characters",
    )
    op.create_check_constraint(
        "ck_timeline_day_position",
        "timeline_days",
        "position >= 1",
        schema="characters",
    )
    op.create_foreign_key(
        "fk_timeline_day_owner",
        "timeline_days",
        "timelines",
        ["continuity_id", "identity_id", "persona_id"],
        ["continuity_id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_foreign_key(
        "fk_timeline_day_conversation",
        "timeline_days",
        "conversations",
        ["conversation_id", "continuity_id", "identity_id", "persona_id", "mode"],
        ["id", "continuity_id", "identity_id", "persona_id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_foreign_key(
        "fk_timeline_day_settled_leaf",
        "timeline_days",
        "messages",
        ["settled_selected_leaf_id", "conversation_id", "continuity_id"],
        ["id", "conversation_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.drop_column("timeline_days", "entry_mode", schema="characters")


def _add_shared_columns(table: str) -> None:
    """Add nullable shared columns before exact Entry backfill.

    Args:
        table:
            Subtype table being restored.
    """

    for column in (
        sa.Column("continuity_id", sa.Uuid(), nullable=True),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("persona_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
    ):
        op.add_column(table, column, schema="characters")


def _require_shared_columns(table: str) -> None:
    """Make fully backfilled shared columns non-nullable.

    Args:
        table:
            Subtype table being restored.
    """

    for column in (
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
        "mode",
        "position",
    ):
        op.alter_column(table, column, nullable=False, schema="characters")


def _point_memory_at_subtypes() -> None:
    """Restore the prior mode-specific memory foreign keys."""

    _create_memory_foreign_keys("subtypes")


def _create_memory_foreign_keys(target: str) -> None:
    """Create transitional memory provenance constraints.

    Args:
        target:
            Parent Entry table or the prior subtype relations.
    """

    scene_table = "continuity_entries" if target == "continuity_entries" else "scenes"
    day_table = (
        "continuity_entries" if target == "continuity_entries" else "timeline_days"
    )
    complete_remote = [
        "id",
        "continuity_id",
        "identity_id",
        "persona_id",
        "conversation_id",
    ]
    owner_remote = ["id", "continuity_id", "identity_id", "persona_id"]
    for table, name, local, remote_table, remote in (
        (
            "memory_evidence",
            "fk_memory_evidence_scene",
            [
                "scene_id",
                "continuity_id",
                "identity_id",
                "persona_id",
                "conversation_id",
            ],
            scene_table,
            complete_remote,
        ),
        (
            "memory_evidence",
            "fk_memory_evidence_day",
            ["day_id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
            day_table,
            complete_remote,
        ),
        (
            "memory_evidence",
            "fk_memory_evidence_occurrence_scene",
            ["occurrence_scene_id", "continuity_id", "identity_id", "persona_id"],
            scene_table,
            owner_remote,
        ),
        (
            "memory_evidence",
            "fk_memory_evidence_occurrence_day",
            ["occurrence_day_id", "continuity_id", "identity_id", "persona_id"],
            day_table,
            owner_remote,
        ),
        (
            "memory_extraction_effects",
            "fk_memory_effect_scene",
            [
                "scene_id",
                "continuity_id",
                "identity_id",
                "persona_id",
                "conversation_id",
            ],
            scene_table,
            complete_remote,
        ),
        (
            "memory_extraction_effects",
            "fk_memory_effect_day",
            ["day_id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
            day_table,
            complete_remote,
        ),
    ):
        op.create_foreign_key(
            name,
            table,
            remote_table,
            local,
            remote,
            source_schema="characters",
            referent_schema="characters",
        )
