"""Persist evolution effects, events, and current projections.

Revision ID: 24d7a1c9e5b3
Revises: b17c4e92a6d1
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "24d7a1c9e5b3"
down_revision: str | Sequence[str] | None = "b17c4e92a6d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add authoritative evolution history and rebuildable projection caches."""

    op.create_table(
        "evolution_effects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_persona_message_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=True),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "continuity_id", name="uq_evolution_effect_ownership"
        ),
        sa.UniqueConstraint(
            "source_persona_message_id", name="uq_evolution_effect_source"
        ),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_evolution_effect_owner",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            [
                "characters.conversations.id",
                "characters.conversations.continuity_id",
            ],
            name="fk_evolution_effect_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["source_persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_evolution_effect_source",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'no_change', 'applied', 'rejected')",
            name="ck_evolution_effect_state",
        ),
        sa.CheckConstraint(
            "(state = 'reserved' AND proposal IS NULL AND decision IS NULL AND completed_at IS NULL) OR "
            "(state <> 'reserved' AND proposal IS NOT NULL AND decision IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_evolution_effect_terminal",
        ),
        schema="characters",
    )
    op.create_table(
        "evolution_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("relationship_revision", sa.Integer(), nullable=False),
        sa.Column("adaptation_revision", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "continuity_id", name="uq_evolution_event_ownership"),
        sa.UniqueConstraint(
            "effect_id", "position", name="uq_evolution_event_effect_position"
        ),
        sa.UniqueConstraint(
            "continuity_id",
            "relationship_revision",
            "adaptation_revision",
            name="uq_evolution_event_replay_position",
        ),
        sa.ForeignKeyConstraint(
            ["effect_id", "continuity_id"],
            [
                "characters.evolution_effects.id",
                "characters.evolution_effects.continuity_id",
            ],
            name="fk_evolution_event_effect",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("position > 0", name="ck_evolution_event_position"),
        sa.CheckConstraint(
            "relationship_revision >= 0 AND adaptation_revision >= 0",
            name="ck_evolution_event_revisions",
        ),
        schema="characters",
    )
    op.create_table(
        "relationship_projections",
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("rebuild_checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("continuity_id"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_relationship_projection_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_relationship_projection_revision"),
        schema="characters",
    )
    op.create_table(
        "persona_adaptation_projections",
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("rebuild_checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("continuity_id"),
        sa.ForeignKeyConstraint(
            ["continuity_id", "identity_id", "persona_id"],
            [
                "characters.continuities.id",
                "characters.continuities.identity_id",
                "characters.continuities.persona_id",
            ],
            name="fk_adaptation_projection_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_adaptation_projection_revision"),
        schema="characters",
    )
    op.create_foreign_key(
        "fk_relationship_projection_checkpoint",
        "relationship_projections",
        "evolution_events",
        ["rebuild_checkpoint_id", "continuity_id"],
        ["id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_adaptation_projection_checkpoint",
        "persona_adaptation_projections",
        "evolution_events",
        ["rebuild_checkpoint_id", "continuity_id"],
        ["id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
        use_alter=True,
    )


def downgrade() -> None:
    """Remove evolution caches before their authoritative history."""

    op.drop_constraint(
        "fk_adaptation_projection_checkpoint",
        "persona_adaptation_projections",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_relationship_projection_checkpoint",
        "relationship_projections",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_table("persona_adaptation_projections", schema="characters")
    op.drop_table("relationship_projections", schema="characters")
    op.drop_table("evolution_events", schema="characters")
    op.drop_table("evolution_effects", schema="characters")
