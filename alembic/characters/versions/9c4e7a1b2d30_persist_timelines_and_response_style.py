"""Persist Timelines, represented days, and response-style state.

Revision ID: 9c4e7a1b2d30
Revises: 7a9c2e4f6b81
Create Date: 2026-11-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4e7a1b2d30"
down_revision: str | Sequence[str] | None = "7a9c2e4f6b81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Timeline ownership, calendar facts, and style provenance."""

    op.drop_constraint(
        "ck_conversation_mode", "conversations", schema="characters", type_="check"
    )
    op.create_check_constraint(
        "ck_conversation_mode",
        "conversations",
        "mode IN ('ongoing', 'storyline', 'timeline')",
        schema="characters",
    )
    op.create_index(
        "uq_active_timeline_pair",
        "continuities",
        ["identity_id", "persona_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("mode = 'timeline' AND lifecycle = 'active'"),
    )
    op.create_table(
        "response_style_settings",
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("scene_description", sa.String(16), nullable=False),
        sa.Column("response_length", sa.String(16), nullable=False),
        sa.Column("narrative_placement", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("continuity_id"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_response_style_owner",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_response_style_revision"),
        sa.CheckConstraint(
            "scene_description IN ('none', 'light', 'balanced', 'rich')",
            name="ck_response_style_scene_description",
        ),
        sa.CheckConstraint(
            "response_length IN ('concise', 'balanced', 'expansive')",
            name="ck_response_style_response_length",
        ),
        sa.CheckConstraint(
            "narrative_placement IN ('before_dialogue', 'interleaved', 'after_dialogue')",
            name="ck_response_style_narrative_placement",
        ),
        schema="characters",
    )
    op.execute("""
        INSERT INTO characters.response_style_settings (
            continuity_id, identity_id, persona_id, scene_description,
            response_length, narrative_placement, revision
        )
        SELECT id, identity_id, persona_id,
               CASE WHEN mode = 'ongoing' THEN 'none' ELSE 'balanced' END,
               'balanced', 'interleaved', 1
        FROM characters.continuities
        """)
    op.create_table(
        "timelines",
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("calendar_timezone", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("continuity_id"),
        sa.UniqueConstraint(
            "continuity_id", "identity_id", "persona_id", name="uq_timeline_ownership"
        ),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id", "mode"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
                "characters.continuities.mode",
            ],
            name="fk_timeline_continuity",
        ),
        sa.CheckConstraint("mode = 'timeline'", name="ck_timeline_mode"),
        sa.CheckConstraint("revision >= 1", name="ck_timeline_revision"),
        schema="characters",
    )
    op.create_table(
        "timeline_days",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("boundary_timezone", sa.String(64), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_selected_leaf_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_timeline_day_ownership",
        ),
        sa.UniqueConstraint(
            "continuity_id", "position", name="uq_timeline_day_position"
        ),
        sa.UniqueConstraint("continuity_id", "local_date", name="uq_timeline_day_date"),
        sa.UniqueConstraint("conversation_id", name="uq_timeline_day_conversation"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.timelines.continuity_id",
                "characters.timelines.identity_id",
                "characters.timelines.persona_id",
            ],
            name="fk_timeline_day_owner",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "continuity_id", "identity_id", "persona_id", "mode"],
            [
                "characters.conversations.id",
                "characters.conversations.continuity_id",
                "characters.conversations.identity_id",
                "characters.conversations.persona_id",
                "characters.conversations.mode",
            ],
            name="fk_timeline_day_conversation",
        ),
        sa.CheckConstraint("mode = 'timeline'", name="ck_timeline_day_mode"),
        sa.CheckConstraint("position >= 1", name="ck_timeline_day_position"),
        sa.CheckConstraint("opens_at < closes_at", name="ck_timeline_day_boundary"),
        sa.CheckConstraint(
            "(closed_at IS NULL AND settled_selected_leaf_id IS NULL) OR "
            "(closed_at IS NOT NULL AND closed_at >= closes_at AND settled_selected_leaf_id IS NOT NULL)",
            name="ck_timeline_day_closure",
        ),
        schema="characters",
    )
    op.create_foreign_key(
        "fk_timeline_day_settled_leaf",
        "timeline_days",
        "messages",
        ["settled_selected_leaf_id", "conversation_id", "continuity_id"],
        ["id", "conversation_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
        use_alter=True,
    )
    op.add_column(
        "generation_attempts",
        sa.Column("response_style", sa.JSON(), nullable=True),
        schema="characters",
    )
    op.execute("""
        UPDATE characters.generation_attempts AS attempt
        SET response_style = COALESCE(
            message.response_provenance -> 'response_style',
            json_build_object(
                'name', 'characters.response_style',
                'version', '1.0.0',
                'scene_description', CASE WHEN conversation.mode = 'ongoing' THEN 'none' ELSE 'balanced' END,
                'response_length', 'balanced',
                'narrative_placement', 'interleaved',
                'source_revision', 1,
                'instruction', 'Legacy response style retained during Stage 8 persistence migration.'
            )
        )
        FROM characters.conversations AS conversation
        LEFT JOIN characters.messages AS message ON message.id = attempt.persona_message_id
        WHERE conversation.id = attempt.conversation_id
          AND conversation.continuity_id = attempt.continuity_id
        """)
    op.alter_column(
        "generation_attempts", "response_style", nullable=False, schema="characters"
    )


def downgrade() -> None:
    """Remove Timeline and style state while retaining older mode records."""

    op.drop_column("generation_attempts", "response_style", schema="characters")
    op.drop_constraint(
        "fk_timeline_day_settled_leaf",
        "timeline_days",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_table("timeline_days", schema="characters")
    op.drop_table("timelines", schema="characters")
    op.drop_table("response_style_settings", schema="characters")
    op.drop_index(
        "uq_active_timeline_pair", table_name="continuities", schema="characters"
    )
    op.drop_constraint(
        "ck_conversation_mode", "conversations", schema="characters", type_="check"
    )
    op.create_check_constraint(
        "ck_conversation_mode",
        "conversations",
        "mode IN ('ongoing', 'storyline')",
        schema="characters",
    )
