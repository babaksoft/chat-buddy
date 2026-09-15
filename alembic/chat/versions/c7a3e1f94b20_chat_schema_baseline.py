"""Create the Chat schema baseline.

Revision ID: c7a3e1f94b20
Revises:
Create Date: 2026-09-16 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a3e1f94b20"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAT_SCHEMA = "chat"


def upgrade() -> None:
    """Create the current Chat tables in the Chat schema."""

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=CHAT_SCHEMA,
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        op.f("ix_chat_memories_key"),
        "memories",
        ["key"],
        unique=True,
        schema=CHAT_SCHEMA,
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "system",
                "user",
                "assistant",
                name="messagerole",
                schema=CHAT_SCHEMA,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{CHAT_SCHEMA}.conversations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=CHAT_SCHEMA,
    )


def downgrade() -> None:
    """Remove the Chat tables while retaining Alembic's schema container."""

    op.drop_table("messages", schema=CHAT_SCHEMA)
    sa.Enum(
        "system",
        "user",
        "assistant",
        name="messagerole",
        schema=CHAT_SCHEMA,
    ).drop(op.get_bind())
    op.drop_index(
        op.f("ix_chat_memories_key"),
        table_name="memories",
        schema=CHAT_SCHEMA,
    )
    op.drop_table("memories", schema=CHAT_SCHEMA)
    op.drop_table("conversations", schema=CHAT_SCHEMA)
