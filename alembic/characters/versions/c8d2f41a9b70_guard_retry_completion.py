"""Guard retry completion against its selected response.

Revision ID: c8d2f41a9b70
Revises: 3f8b2c4d6e7a
Create Date: 2026-10-06 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d2f41a9b70"
down_revision: str | Sequence[str] | None = "3f8b2c4d6e7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the selected-leaf guard used by response attempts."""

    op.add_column(
        "generation_attempts",
        sa.Column("selection_guard_id", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.execute("""
        UPDATE characters.generation_attempts
        SET selection_guard_id = user_message_id
        """)
    op.alter_column(
        "generation_attempts",
        "selection_guard_id",
        nullable=False,
        schema="characters",
    )
    op.create_foreign_key(
        "fk_attempt_selection_guard",
        "generation_attempts",
        "messages",
        ["selection_guard_id", "conversation_id", "continuity_id"],
        ["id", "conversation_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
    )


def downgrade() -> None:
    """Remove retry completion guards."""

    op.drop_constraint(
        "fk_attempt_selection_guard",
        "generation_attempts",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_column("generation_attempts", "selection_guard_id", schema="characters")
