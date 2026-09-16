"""Create the Characters schema baseline.

Revision ID: 61a5c7060ad9
Revises:
Create Date: 2026-09-16 00:00:00

"""

from collections.abc import Sequence

revision: str = "61a5c7060ad9"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish the empty Characters migration history."""


def downgrade() -> None:
    """Remove the empty Characters migration revision."""
