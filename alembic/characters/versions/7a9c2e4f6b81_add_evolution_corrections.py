"""Add append-only evolution correction events.

Revision ID: 7a9c2e4f6b81
Revises: 24d7a1c9e5b3
Create Date: 2026-10-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a9c2e4f6b81"
down_revision: str | Sequence[str] | None = "24d7a1c9e5b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable user corrections beside inferred evolution events."""

    op.create_table(
        "evolution_correction_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("target_event_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("replacement", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=1024), nullable=False),
        sa.Column("expected_relationship_revision", sa.Integer(), nullable=False),
        sa.Column("expected_adaptation_revision", sa.Integer(), nullable=False),
        sa.Column("relationship_revision", sa.Integer(), nullable=False),
        sa.Column("adaptation_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('exclude', 'replace', 'restore')",
            name="ck_evolution_correction_action",
        ),
        sa.CheckConstraint(
            "(action = 'replace' AND replacement IS NOT NULL) OR "
            "(action <> 'replace' AND replacement IS NULL)",
            name="ck_evolution_correction_replacement",
        ),
        sa.CheckConstraint(
            "expected_relationship_revision >= 0 AND "
            "expected_adaptation_revision >= 0 AND "
            "relationship_revision >= 0 AND adaptation_revision >= 0",
            name="ck_evolution_correction_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_evolution_correction_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_event_id", "continuity_id"],
            [
                "characters.evolution_events.id",
                "characters.evolution_events.continuity_id",
            ],
            name="fk_evolution_correction_target",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "continuity_id", name="uq_evolution_correction_ownership"
        ),
        sa.UniqueConstraint(
            "continuity_id",
            "relationship_revision",
            "adaptation_revision",
            name="uq_evolution_correction_replay_position",
        ),
        schema="characters",
    )


def downgrade() -> None:
    """Remove evolution correction events."""

    op.drop_table("evolution_correction_events", schema="characters")
