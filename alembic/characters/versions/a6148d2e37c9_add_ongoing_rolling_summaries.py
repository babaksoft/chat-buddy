"""Add Ongoing rolling summaries

Revision ID: a6148d2e37c9
Revises: f71d92ab0c55
Create Date: 2026-10-02 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6148d2e37c9"
down_revision: str | Sequence[str] | None = "f71d92ab0c55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable ownership-constrained summary revisions."""

    op.create_table(
        "summary_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), nullable=True),
        sa.Column("checkpoint_message_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generation", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(content) > 0", name="ck_summary_content"),
        sa.CheckConstraint("revision > 0", name="ck_summary_revision"),
        sa.ForeignKeyConstraint(
            ["checkpoint_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_summary_checkpoint",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_summary_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id", "conversation_id", "continuity_id"],
            [
                "characters.summary_revisions.id",
                "characters.summary_revisions.conversation_id",
                "characters.summary_revisions.continuity_id",
            ],
            name="fk_summary_predecessor",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "conversation_id", "continuity_id", name="uq_summary_ownership"
        ),
        sa.UniqueConstraint("conversation_id", "revision", name="uq_summary_revision"),
        sa.UniqueConstraint("predecessor_id", name="uq_summary_successor"),
        schema="characters",
    )
    op.create_index(
        "uq_active_conversation_summary",
        "summary_revisions",
        ["conversation_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    """Remove all Ongoing summary revisions."""

    op.drop_index(
        "uq_active_conversation_summary",
        table_name="summary_revisions",
        schema="characters",
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )
    op.drop_table("summary_revisions", schema="characters")
