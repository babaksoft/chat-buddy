"""Persist linear retries, summaries, and memory lifecycle.

Revision ID: d4a9f12c6b30
Revises: 82e6c4f63a91
Create Date: 2026-09-19 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a9f12c6b30"
down_revision: str | Sequence[str] | None = "82e6c4f63a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAT_SCHEMA = "chat"


def upgrade() -> None:
    """Create final Stage 3 persistence objects in the Chat schema."""

    op.add_column(
        "generation_attempts",
        sa.Column("submitted_user_content", sa.Text(), nullable=False),
        schema=CHAT_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_message_id_conversation",
        "messages",
        ["id", "conversation_id"],
        schema=CHAT_SCHEMA,
    )
    op.drop_constraint(
        "generation_attempts_source_user_message_id_fkey",
        "generation_attempts",
        schema=CHAT_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "generation_attempts_assistant_message_id_fkey",
        "generation_attempts",
        schema=CHAT_SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_generation_attempt_source_conversation",
        "generation_attempts",
        "messages",
        ["source_user_message_id", "conversation_id"],
        ["id", "conversation_id"],
        source_schema=CHAT_SCHEMA,
        referent_schema=CHAT_SCHEMA,
    )
    op.create_foreign_key(
        "fk_generation_attempt_assistant_conversation",
        "generation_attempts",
        "messages",
        ["assistant_message_id", "conversation_id"],
        ["id", "conversation_id"],
        source_schema=CHAT_SCHEMA,
        referent_schema=CHAT_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_generation_attempt_id_status",
        "generation_attempts",
        ["id", "status"],
        schema=CHAT_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_generation_attempt_memory_source",
        "generation_attempts",
        [
            "id",
            "conversation_id",
            "source_user_message_id",
            "assistant_message_id",
            "status",
        ],
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        "uq_generation_attempt_open_conversation",
        "generation_attempts",
        ["conversation_id"],
        unique=True,
        schema=CHAT_SCHEMA,
        postgresql_where=sa.text("status IN ('pending', 'streaming')"),
    )

    summary_lifecycle = postgresql.ENUM(
        "active",
        "superseded",
        name="summarylifecycle",
        schema=CHAT_SCHEMA,
        create_type=False,
    )
    summary_lifecycle.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("lifecycle", summary_lifecycle, nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), nullable=True),
        sa.Column("checkpoint_message_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "predecessor_id IS NULL OR predecessor_id != id",
            name="ck_summary_not_own_predecessor",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{CHAT_SCHEMA}.conversations.id"],
            name="fk_summary_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_message_id", "conversation_id"],
            [f"{CHAT_SCHEMA}.messages.id", f"{CHAT_SCHEMA}.messages.conversation_id"],
            name="fk_summary_checkpoint_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id", "conversation_id"],
            [f"{CHAT_SCHEMA}.summaries.id", f"{CHAT_SCHEMA}.summaries.conversation_id"],
            name="fk_summary_predecessor_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "conversation_id", name="uq_summary_id_conversation"
        ),
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        "ix_chat_summaries_conversation_id",
        "summaries",
        ["conversation_id"],
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        "ix_chat_summaries_checkpoint_message_id",
        "summaries",
        ["checkpoint_message_id"],
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        "uq_summary_active_conversation",
        "summaries",
        ["conversation_id"],
        unique=True,
        schema=CHAT_SCHEMA,
        postgresql_where=sa.text("lifecycle = 'active'"),
    )

    op.drop_index(
        op.f("ix_chat_memories_key"),
        table_name="memories",
        schema=CHAT_SCHEMA,
    )
    op.drop_table("memories", schema=CHAT_SCHEMA)

    memory_lifecycle = postgresql.ENUM(
        "active",
        "excluded",
        "superseded",
        name="memorylifecycle",
        schema=CHAT_SCHEMA,
        create_type=False,
    )
    memory_origin_kind = postgresql.ENUM(
        "extracted",
        "user_correction",
        name="memoryoriginkind",
        schema=CHAT_SCHEMA,
        create_type=False,
    )
    extraction_outcome = postgresql.ENUM(
        "succeeded",
        "exhausted",
        name="memoryextractionoutcome",
        schema=CHAT_SCHEMA,
        create_type=False,
    )
    generation_status = postgresql.ENUM(
        "pending",
        "streaming",
        "completed",
        "failed",
        "interrupted",
        name="generationattemptstatus",
        schema=CHAT_SCHEMA,
        create_type=False,
    )
    memory_lifecycle.create(op.get_bind(), checkfirst=True)
    memory_origin_kind.create(op.get_bind(), checkfirst=True)
    extraction_outcome.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "memories",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("lifecycle", memory_lifecycle, nullable=False),
        sa.Column("origin_kind", memory_origin_kind, nullable=False),
        sa.Column("source_available", sa.Boolean(), nullable=False),
        sa.Column("source_conversation_id", sa.Uuid(), nullable=True),
        sa.Column("source_user_message_id", sa.Uuid(), nullable=True),
        sa.Column("source_assistant_message_id", sa.Uuid(), nullable=True),
        sa.Column("source_generation_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("source_generation_status", generation_status, nullable=True),
        sa.Column("superseded_revision_id", sa.Uuid(), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(origin_kind = 'extracted' AND superseded_revision_id IS NULL "
            "AND corrected_at IS NULL AND ((source_available = true "
            "AND source_conversation_id IS NOT NULL "
            "AND source_user_message_id IS NOT NULL "
            "AND source_assistant_message_id IS NOT NULL "
            "AND source_generation_attempt_id IS NOT NULL "
            "AND source_generation_status = 'completed') OR "
            "(source_available = false AND source_conversation_id IS NULL "
            "AND source_user_message_id IS NULL "
            "AND source_assistant_message_id IS NULL "
            "AND source_generation_attempt_id IS NULL "
            "AND source_generation_status IS NULL))) OR "
            "(origin_kind = 'user_correction' AND source_available = true "
            "AND source_conversation_id IS NULL AND source_user_message_id IS NULL "
            "AND source_assistant_message_id IS NULL "
            "AND source_generation_attempt_id IS NULL "
            "AND source_generation_status IS NULL "
            "AND superseded_revision_id IS NOT NULL AND corrected_at IS NOT NULL)",
            name="ck_memory_origin",
        ),
        sa.CheckConstraint(
            "superseded_revision_id IS NULL OR superseded_revision_id != revision_id",
            name="ck_memory_not_self_correction",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_generation_attempt_id",
                "source_conversation_id",
                "source_user_message_id",
                "source_assistant_message_id",
                "source_generation_status",
            ],
            [
                f"{CHAT_SCHEMA}.generation_attempts.id",
                f"{CHAT_SCHEMA}.generation_attempts.conversation_id",
                f"{CHAT_SCHEMA}.generation_attempts.source_user_message_id",
                f"{CHAT_SCHEMA}.generation_attempts.assistant_message_id",
                f"{CHAT_SCHEMA}.generation_attempts.status",
            ],
            name="fk_memory_completed_source",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_revision_id"],
            [f"{CHAT_SCHEMA}.memories.revision_id"],
            name="fk_memory_corrected_revision",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        "ix_chat_memories_memory_id",
        "memories",
        ["memory_id"],
        schema=CHAT_SCHEMA,
    )
    op.create_index(
        "uq_memory_current_lineage",
        "memories",
        ["memory_id"],
        unique=True,
        schema=CHAT_SCHEMA,
        postgresql_where=sa.text("lifecycle != 'superseded'"),
    )
    op.create_index(
        "uq_memory_current_subject",
        "memories",
        ["subject"],
        unique=True,
        schema=CHAT_SCHEMA,
        postgresql_where=sa.text("lifecycle != 'superseded'"),
    )
    op.create_index(
        "ix_memory_eligible_order",
        "memories",
        ["lifecycle", "created_at", "revision_id"],
        schema=CHAT_SCHEMA,
    )

    op.create_table(
        "memory_extraction_receipts",
        sa.Column("generation_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("generation_attempt_status", generation_status, nullable=False),
        sa.Column("outcome", extraction_outcome, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation_attempt_status = 'completed'",
            name="ck_extraction_receipt_completed_attempt",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 1 AND 3",
            name="ck_extraction_receipt_attempt_count",
        ),
        sa.CheckConstraint(
            "outcome != 'exhausted' OR attempt_count = 3",
            name="ck_extraction_receipt_exhausted_count",
        ),
        sa.ForeignKeyConstraint(
            ["generation_attempt_id", "generation_attempt_status"],
            [
                f"{CHAT_SCHEMA}.generation_attempts.id",
                f"{CHAT_SCHEMA}.generation_attempts.status",
            ],
            name="fk_extraction_receipt_completed_attempt",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("generation_attempt_id"),
        schema=CHAT_SCHEMA,
    )


def downgrade() -> None:
    """Restore the empty prototype memory schema and Stage 2 attempts."""

    op.drop_table("memory_extraction_receipts", schema=CHAT_SCHEMA)
    op.drop_index("ix_memory_eligible_order", table_name="memories", schema=CHAT_SCHEMA)
    op.drop_index(
        "uq_memory_current_subject", table_name="memories", schema=CHAT_SCHEMA
    )
    op.drop_index(
        "uq_memory_current_lineage", table_name="memories", schema=CHAT_SCHEMA
    )
    op.drop_index(
        "ix_chat_memories_memory_id", table_name="memories", schema=CHAT_SCHEMA
    )
    op.drop_table("memories", schema=CHAT_SCHEMA)
    postgresql.ENUM(
        name="memoryextractionoutcome", schema=CHAT_SCHEMA
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="memoryoriginkind", schema=CHAT_SCHEMA).drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="memorylifecycle", schema=CHAT_SCHEMA).drop(
        op.get_bind(), checkfirst=True
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

    op.drop_index(
        "uq_summary_active_conversation",
        table_name="summaries",
        schema=CHAT_SCHEMA,
    )
    op.drop_index(
        "ix_chat_summaries_checkpoint_message_id",
        table_name="summaries",
        schema=CHAT_SCHEMA,
    )
    op.drop_index(
        "ix_chat_summaries_conversation_id",
        table_name="summaries",
        schema=CHAT_SCHEMA,
    )
    op.drop_table("summaries", schema=CHAT_SCHEMA)
    postgresql.ENUM(name="summarylifecycle", schema=CHAT_SCHEMA).drop(
        op.get_bind(), checkfirst=True
    )

    op.drop_index(
        "uq_generation_attempt_open_conversation",
        table_name="generation_attempts",
        schema=CHAT_SCHEMA,
    )
    op.drop_constraint(
        "uq_generation_attempt_memory_source",
        "generation_attempts",
        schema=CHAT_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "uq_generation_attempt_id_status",
        "generation_attempts",
        schema=CHAT_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_generation_attempt_assistant_conversation",
        "generation_attempts",
        schema=CHAT_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_generation_attempt_source_conversation",
        "generation_attempts",
        schema=CHAT_SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "generation_attempts_source_user_message_id_fkey",
        "generation_attempts",
        "messages",
        ["source_user_message_id"],
        ["id"],
        source_schema=CHAT_SCHEMA,
        referent_schema=CHAT_SCHEMA,
    )
    op.create_foreign_key(
        "generation_attempts_assistant_message_id_fkey",
        "generation_attempts",
        "messages",
        ["assistant_message_id"],
        ["id"],
        source_schema=CHAT_SCHEMA,
        referent_schema=CHAT_SCHEMA,
    )
    op.drop_constraint(
        "uq_message_id_conversation",
        "messages",
        schema=CHAT_SCHEMA,
        type_="unique",
    )
    op.drop_column(
        "generation_attempts", "submitted_user_content", schema=CHAT_SCHEMA
    )
