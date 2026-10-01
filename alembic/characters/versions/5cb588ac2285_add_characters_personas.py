"""Add Characters personas

Revision ID: 5cb588ac2285
Revises: d9fa8117ca0c
Create Date: 2026-10-01 13:22:38.173392

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5cb588ac2285"
down_revision: str | Sequence[str] | None = "d9fa8117ca0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Characters-owned global persona table."""

    op.create_table(
        "personas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("definition", sa.String(length=8192), nullable=False),
        sa.Column("traits", sa.String(length=4096), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_frozen", sa.Boolean(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_persona_revision"),
        sa.PrimaryKeyConstraint("id"),
        schema="characters",
    )


def downgrade() -> None:
    """Remove personas while retaining the prior identity revision."""

    op.drop_table("personas", schema="characters")
