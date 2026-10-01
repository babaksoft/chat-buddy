"""Add Characters identities

Revision ID: d9fa8117ca0c
Revises: 61a5c7060ad9
Create Date: 2026-10-01 09:56:30.847659

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9fa8117ca0c"
down_revision: str | Sequence[str] | None = "61a5c7060ad9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Characters-owned identity table."""

    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("gender", sa.String(length=64), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("pronouns", sa.String(length=64), nullable=True),
        sa.Column("preferred_address", sa.String(length=128), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_frozen", sa.Boolean(), nullable=False),
        sa.Column("default_key", sa.String(length=3), nullable=True),
        sa.CheckConstraint(
            "default_key IS NULL OR default_key = 'you'", name="ck_identity_default"
        ),
        sa.CheckConstraint("age >= 0 AND age <= 130", name="ck_identity_age"),
        sa.CheckConstraint(
            "age IS NULL OR birth_date IS NULL", name="ck_identity_age_date"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_identity_revision"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("default_key"),
        schema="characters",
    )


def downgrade() -> None:
    """Remove identities while retaining the Characters baseline."""

    op.drop_table("identities", schema="characters")
