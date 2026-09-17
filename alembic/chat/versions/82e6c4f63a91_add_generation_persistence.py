"""Add Chat generation defaults and attempt persistence.

Revision ID: 82e6c4f63a91
Revises: c7a3e1f94b20
Create Date: 2026-09-17 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "82e6c4f63a91"
down_revision: str | Sequence[str] | None = "c7a3e1f94b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAT_SCHEMA = "chat"


def upgrade() -> None:
    """Add conversation defaults and durable generation attempts."""

    op.add_column(
        "conversations",
        sa.Column("provider_id", sa.String(length=255), nullable=True),
        schema=CHAT_SCHEMA,
    )
    op.add_column(
        "conversations",
        sa.Column("model_id", sa.String(length=255), nullable=True),
        schema=CHAT_SCHEMA,
    )
    op.add_column(
        "conversations",
        sa.Column(
            "requested_generation_configuration",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        schema=CHAT_SCHEMA,
    )
    op.alter_column(
        "conversations",
        "requested_generation_configuration",
        server_default=None,
        schema=CHAT_SCHEMA,
    )

    op.create_table(
        "generation_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_user_message_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(length=255), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("effective_configuration", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "streaming",
                "completed",
                "failed",
                "interrupted",
                name="generationattemptstatus",
                schema=CHAT_SCHEMA,
            ),
            nullable=False,
        ),
        sa.Column("partial_content", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) "
            "OR (status = 'streaming' AND started_at IS NOT NULL "
            "AND finished_at IS NULL) OR (status IN ('completed', 'failed', "
            "'interrupted') AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_generation_attempt_lifecycle_timestamps",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND assistant_message_id IS NOT NULL "
            "AND partial_content IS NULL) OR "
            "(status != 'completed' AND assistant_message_id IS NULL)",
            name="ck_generation_attempt_completed_message",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL) OR "
            "(status != 'failed' AND error_code IS NULL AND error_detail IS NULL)",
            name="ck_generation_attempt_failure_information",
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            [f"{CHAT_SCHEMA}.messages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{CHAT_SCHEMA}.conversations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_user_message_id"],
            [f"{CHAT_SCHEMA}.messages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assistant_message_id"),
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        op.f("ix_chat_generation_attempts_conversation_id"),
        "generation_attempts",
        ["conversation_id"],
        unique=False,
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        op.f("ix_chat_generation_attempts_source_user_message_id"),
        "generation_attempts",
        ["source_user_message_id"],
        unique=False,
        schema=CHAT_SCHEMA,
    )


def downgrade() -> None:
    """Remove generation attempts and conversation generation defaults."""

    op.drop_index(
        op.f("ix_chat_generation_attempts_source_user_message_id"),
        table_name="generation_attempts",
        schema=CHAT_SCHEMA,
    )
    op.drop_index(
        op.f("ix_chat_generation_attempts_conversation_id"),
        table_name="generation_attempts",
        schema=CHAT_SCHEMA,
    )
    op.drop_table("generation_attempts", schema=CHAT_SCHEMA)
    sa.Enum(
        "pending",
        "streaming",
        "completed",
        "failed",
        "interrupted",
        name="generationattemptstatus",
        schema=CHAT_SCHEMA,
    ).drop(op.get_bind())
    op.drop_column(
        "conversations",
        "requested_generation_configuration",
        schema=CHAT_SCHEMA,
    )
    op.drop_column("conversations", "model_id", schema=CHAT_SCHEMA)
    op.drop_column("conversations", "provider_id", schema=CHAT_SCHEMA)
