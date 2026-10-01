"""Add Ongoing continuity lifecycle and starting relationship snapshots.

Revision ID: 83a2c09d7f41
Revises: 5cb588ac2285
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "83a2c09d7f41"
down_revision: str | Sequence[str] | None = "5cb588ac2285"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create continuity and ownership-constrained Ongoing child records."""

    op.create_table(
        "continuities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_request", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
        sa.UniqueConstraint(
            "id", "identity_id", "persona_id", name="uq_continuity_ownership"
        ),
        sa.ForeignKeyConstraint(["identity_id"], ["characters.identities.id"]),
        sa.ForeignKeyConstraint(["persona_id"], ["characters.personas.id"]),
        sa.CheckConstraint(
            "mode IN ('ongoing', 'storyline', 'timeline')", name="ck_continuity_mode"
        ),
        sa.CheckConstraint(
            "lifecycle IN ('active', 'archived')", name="ck_continuity_lifecycle"
        ),
        schema="characters",
    )
    op.create_index(
        "uq_active_ongoing_pair",
        "continuities",
        ["identity_id", "persona_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("mode = 'ongoing' AND lifecycle = 'active'"),
        sqlite_where=sa.text("mode = 'ongoing' AND lifecycle = 'active'"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("continuity_id"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_conversation_ownership",
        ),
        schema="characters",
    )
    op.create_table(
        "starting_relationships",
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("continuity_id"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_starting_relationship_ownership",
        ),
        schema="characters",
    )


def downgrade() -> None:
    """Remove continuity records while preserving frozen profile state."""

    op.drop_table("starting_relationships", schema="characters")
    op.drop_table("conversations", schema="characters")
    op.drop_index(
        "uq_active_ongoing_pair", table_name="continuities", schema="characters"
    )
    op.drop_table("continuities", schema="characters")
