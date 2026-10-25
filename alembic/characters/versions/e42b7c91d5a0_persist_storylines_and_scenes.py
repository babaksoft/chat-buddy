"""Persist named Storylines and ordered scene ownership.

Revision ID: e42b7c91d5a0
Revises: c8d2f41a9b70
Create Date: 2026-10-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e42b7c91d5a0"
down_revision: str | Sequence[str] | None = "c8d2f41a9b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Generalize conversations and add Storyline and scene records."""

    op.create_unique_constraint(
        "uq_continuity_mode_ownership",
        "continuities",
        ["id", "identity_id", "persona_id", "mode"],
        schema="characters",
    )
    op.create_index(
        "uq_active_storyline_pair",
        "continuities",
        ["identity_id", "persona_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("mode = 'storyline' AND lifecycle = 'active'"),
        sqlite_where=sa.text("mode = 'storyline' AND lifecycle = 'active'"),
    )

    op.add_column(
        "conversations",
        sa.Column("mode", sa.String(16), nullable=True),
        schema="characters",
    )
    op.execute("UPDATE characters.conversations SET mode = 'ongoing'")
    op.alter_column("conversations", "mode", nullable=False, schema="characters")
    op.drop_constraint(
        "fk_conversation_ownership",
        "conversations",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_constraint(
        "conversations_continuity_id_key",
        "conversations",
        schema="characters",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_conversation_ownership",
        "conversations",
        "continuities",
        ["continuity_id", "identity_id", "persona_id", "mode"],
        ["id", "identity_id", "persona_id", "mode"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_unique_constraint(
        "uq_conversation_complete_ownership",
        "conversations",
        ["id", "continuity_id", "identity_id", "persona_id", "mode"],
        schema="characters",
    )
    op.create_check_constraint(
        "ck_conversation_mode",
        "conversations",
        "mode IN ('ongoing', 'storyline')",
        schema="characters",
    )
    op.create_index(
        "uq_ongoing_continuity_conversation",
        "conversations",
        ["continuity_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("mode = 'ongoing'"),
        sqlite_where=sa.text("mode = 'ongoing'"),
    )

    op.create_table(
        "storylines",
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("fork_provenance", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("continuity_id"),
        sa.UniqueConstraint(
            "continuity_id",
            "identity_id",
            "persona_id",
            name="uq_storyline_ownership",
        ),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id", "mode"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
                "characters.continuities.mode",
            ],
            name="fk_storyline_continuity",
        ),
        sa.CheckConstraint("mode = 'storyline'", name="ck_storyline_mode"),
        sa.CheckConstraint("revision >= 1", name="ck_storyline_revision"),
        schema="characters",
    )
    op.create_table(
        "scenes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("setup", sa.String(8192), nullable=False),
        sa.Column("response_style", sa.JSON(), nullable=False),
        sa.Column("setup_locked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "continuity_id", "position", name="uq_scene_storyline_position"
        ),
        sa.UniqueConstraint("conversation_id", name="uq_scene_conversation"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.storylines.continuity_id",
                "characters.storylines.identity_id",
                "characters.storylines.persona_id",
            ],
            name="fk_scene_storyline_ownership",
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
            name="fk_scene_conversation_ownership",
        ),
        sa.CheckConstraint("mode = 'storyline'", name="ck_scene_mode"),
        sa.CheckConstraint("position >= 1", name="ck_scene_position"),
        schema="characters",
    )


def downgrade() -> None:
    """Remove Storylines and restore the sole Ongoing conversation shape."""

    op.drop_table("scenes", schema="characters")
    op.drop_table("storylines", schema="characters")
    op.execute("""
        UPDATE characters.conversations
        SET selected_leaf_id = NULL
        WHERE mode = 'storyline'
        """)
    op.execute("""
        DELETE FROM characters.summary_revisions
        WHERE conversation_id IN (
            SELECT id FROM characters.conversations WHERE mode = 'storyline'
        )
        """)
    op.execute("""
        DELETE FROM characters.generation_attempts
        WHERE conversation_id IN (
            SELECT id FROM characters.conversations WHERE mode = 'storyline'
        )
        """)
    op.execute("""
        DELETE FROM characters.messages
        WHERE conversation_id IN (
            SELECT id FROM characters.conversations WHERE mode = 'storyline'
        )
        """)
    op.execute("""
        DELETE FROM characters.starting_relationships
        WHERE continuity_id IN (
            SELECT id FROM characters.continuities WHERE mode = 'storyline'
        )
        """)
    op.execute("DELETE FROM characters.conversations WHERE mode = 'storyline'")
    op.execute("DELETE FROM characters.continuities WHERE mode = 'storyline'")
    op.drop_index(
        "uq_ongoing_continuity_conversation",
        table_name="conversations",
        schema="characters",
    )
    op.drop_constraint(
        "ck_conversation_mode",
        "conversations",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "uq_conversation_complete_ownership",
        "conversations",
        schema="characters",
        type_="unique",
    )
    op.drop_constraint(
        "fk_conversation_ownership",
        "conversations",
        schema="characters",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_conversation_ownership",
        "conversations",
        "continuities",
        ["continuity_id", "identity_id", "persona_id"],
        ["id", "identity_id", "persona_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_unique_constraint(
        "conversations_continuity_id_key",
        "conversations",
        ["continuity_id"],
        schema="characters",
    )
    op.drop_column("conversations", "mode", schema="characters")
    op.drop_index(
        "uq_active_storyline_pair",
        table_name="continuities",
        schema="characters",
    )
    op.drop_constraint(
        "uq_continuity_mode_ownership",
        "continuities",
        schema="characters",
        type_="unique",
    )
