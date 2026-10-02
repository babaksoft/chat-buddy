"""Add durable Ongoing turns

Revision ID: f71d92ab0c55
Revises: 83a2c09d7f41
Create Date: 2026-10-02 18:02:38.546649

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f71d92ab0c55"
down_revision: str | Sequence[str] | None = "83a2c09d7f41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add defaults and ownership-constrained messages and generation attempts."""

    op.add_column(
        "conversations",
        sa.Column("generation_settings", sa.JSON(), nullable=True),
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_conversation_scope",
        "conversations",
        ["id", "continuity_id"],
        schema="characters",
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reply_to", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence > 0 AND ((role = 'user' AND sequence % 2 = 1 AND reply_to IS NULL) OR (role = 'persona' AND sequence % 2 = 0 AND reply_to IS NOT NULL))",
            name="ck_message_path",
        ),
        sa.CheckConstraint("length(content) > 0", name="ck_message_content"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_message_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_message_reply",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_message_sequence"),
        sa.UniqueConstraint(
            "id", "conversation_id", "continuity_id", name="uq_message_ownership"
        ),
        sa.UniqueConstraint("reply_to", name="uq_message_response"),
        schema="characters",
    )
    op.create_table(
        "generation_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("continuity_id", sa.Uuid(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("persona_message_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_input", sa.Text(), nullable=False),
        sa.Column("generation", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("incomplete_output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'completed' AND persona_message_id IS NOT NULL) OR (status <> 'completed' AND persona_message_id IS NULL)",
            name="ck_attempt_completion",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'streaming') AND finished_at IS NULL) OR (status IN ('completed', 'failed', 'interrupted') AND finished_at IS NOT NULL)",
            name="ck_attempt_terminal",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'streaming', 'completed', 'failed', 'interrupted')",
            name="ck_attempt_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "continuity_id"],
            ["characters.conversations.id", "characters.conversations.continuity_id"],
            name="fk_attempt_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["persona_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_attempt_persona",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "continuity_id"],
            [
                "characters.messages.id",
                "characters.messages.conversation_id",
                "characters.messages.continuity_id",
            ],
            name="fk_attempt_user",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("persona_message_id", name="uq_attempt_completion"),
        schema="characters",
    )
    op.create_index(
        "uq_open_conversation_attempt",
        "generation_attempts",
        ["conversation_id"],
        unique=True,
        schema="characters",
        postgresql_where=sa.text("status IN ('pending', 'streaming')"),
        sqlite_where=sa.text("status IN ('pending', 'streaming')"),
    )


def downgrade() -> None:
    """Remove turn records before their conversation ownership constraint."""

    op.drop_index(
        "uq_open_conversation_attempt",
        table_name="generation_attempts",
        schema="characters",
        postgresql_where=sa.text("status IN ('pending', 'streaming')"),
        sqlite_where=sa.text("status IN ('pending', 'streaming')"),
    )
    op.drop_table("generation_attempts", schema="characters")
    op.drop_table("messages", schema="characters")
    op.drop_constraint(
        "uq_conversation_scope", "conversations", schema="characters", type_="unique"
    )
    op.drop_column("conversations", "generation_settings", schema="characters")
