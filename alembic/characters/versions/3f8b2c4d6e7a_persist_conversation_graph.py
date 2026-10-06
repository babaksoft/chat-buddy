"""Persist the Characters conversation graph.

Revision ID: 3f8b2c4d6e7a
Revises: a6148d2e37c9
Create Date: 2026-10-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8b2c4d6e7a"
down_revision: str | Sequence[str] | None = "a6148d2e37c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Convert linear Characters records into one selected graph path."""

    op.add_column(
        "messages",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.add_column(
        "messages",
        sa.Column("response_provenance", sa.JSON(), nullable=True),
        schema="characters",
    )
    op.execute("""
        UPDATE characters.messages AS child
        SET parent_id = parent.id
        FROM characters.messages AS parent
        WHERE parent.conversation_id = child.conversation_id
          AND parent.continuity_id = child.continuity_id
          AND parent.sequence = child.sequence - 1
        """)
    op.execute("""
        UPDATE characters.messages AS message
        SET response_provenance = json_build_object(
            'generation', attempt.generation,
            'response_style', json_build_object(
                'name', 'ongoing.default',
                'version', '1.0.0',
                'instruction', 'Respond as the persona in a natural conversation. Use clear text and preserve the authored identity and relationship boundaries.'
            ),
            'evolution_strategy', json_build_object(
                'name', 'baseline.no_change',
                'version', '1.0.0'
            ),
            'attempt_id', CAST(attempt.id AS text)
        )
        FROM characters.generation_attempts AS attempt
        WHERE attempt.persona_message_id = message.id
          AND message.role = 'persona'
        """)
    op.create_foreign_key(
        "fk_message_parent",
        "messages",
        "messages",
        ["parent_id", "conversation_id", "continuity_id"],
        ["id", "conversation_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_check_constraint(
        "ck_message_role",
        "messages",
        "role IN ('user', 'persona')",
        schema="characters",
    )
    op.create_check_constraint(
        "ck_message_graph_shape",
        "messages",
        "(role = 'user' AND response_provenance IS NULL) OR (role = 'persona' AND parent_id IS NOT NULL AND response_provenance IS NOT NULL)",
        schema="characters",
    )
    op.add_column(
        "conversations",
        sa.Column("selected_leaf_id", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.execute("""
        UPDATE characters.conversations AS conversation
        SET selected_leaf_id = leaf.id
        FROM characters.messages AS leaf
        WHERE leaf.conversation_id = conversation.id
          AND leaf.sequence = (
              SELECT MAX(candidate.sequence)
              FROM characters.messages AS candidate
              WHERE candidate.conversation_id = conversation.id
          )
        """)
    op.create_foreign_key(
        "fk_conversation_selected_leaf",
        "conversations",
        "messages",
        ["selected_leaf_id", "id", "continuity_id"],
        ["id", "conversation_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.drop_constraint(
        "fk_message_reply", "messages", schema="characters", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_message_response", "messages", schema="characters", type_="unique"
    )
    op.drop_constraint(
        "uq_message_sequence", "messages", schema="characters", type_="unique"
    )
    op.drop_constraint(
        "ck_message_path", "messages", schema="characters", type_="check"
    )
    op.drop_column("messages", "reply_to", schema="characters")
    op.drop_column("messages", "sequence", schema="characters")

    op.drop_index(
        "uq_active_conversation_summary",
        table_name="summary_revisions",
        schema="characters",
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )
    op.drop_constraint(
        "uq_summary_successor",
        "summary_revisions",
        schema="characters",
        type_="unique",
    )
    op.drop_constraint(
        "uq_summary_revision",
        "summary_revisions",
        schema="characters",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_summary_checkpoint",
        "summary_revisions",
        ["conversation_id", "checkpoint_message_id"],
        schema="characters",
    )
    op.create_index(
        "ix_summary_conversation_revision",
        "summary_revisions",
        ["conversation_id", "revision"],
        schema="characters",
    )
    op.drop_column("summary_revisions", "checkpoint_sequence", schema="characters")
    op.drop_column("summary_revisions", "is_active", schema="characters")


def downgrade() -> None:
    """Restore a linear schema for an immediately upgraded dataset."""

    op.add_column(
        "messages",
        sa.Column("sequence", sa.Integer(), nullable=True),
        schema="characters",
    )
    op.add_column(
        "messages",
        sa.Column("reply_to", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.execute("""
        WITH RECURSIVE path AS (
            SELECT message.id, message.conversation_id, message.parent_id, 1 AS position
            FROM characters.messages AS message
            WHERE message.parent_id IS NULL
            UNION ALL
            SELECT child.id, child.conversation_id, child.parent_id, path.position + 1
            FROM characters.messages AS child
            JOIN path ON child.parent_id = path.id
        )
        UPDATE characters.messages AS message
        SET sequence = path.position,
            reply_to = CASE WHEN message.role = 'persona' THEN message.parent_id END
        FROM path
        WHERE path.id = message.id
        """)
    op.alter_column("messages", "sequence", nullable=False, schema="characters")
    op.create_unique_constraint(
        "uq_message_sequence",
        "messages",
        ["conversation_id", "sequence"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_message_response", "messages", ["reply_to"], schema="characters"
    )
    op.create_foreign_key(
        "fk_message_reply",
        "messages",
        "messages",
        ["reply_to", "conversation_id", "continuity_id"],
        ["id", "conversation_id", "continuity_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_check_constraint(
        "ck_message_path",
        "messages",
        "sequence > 0 AND ((role = 'user' AND sequence % 2 = 1 AND reply_to IS NULL) OR (role = 'persona' AND sequence % 2 = 0 AND reply_to IS NOT NULL))",
        schema="characters",
    )

    op.add_column(
        "summary_revisions",
        sa.Column("checkpoint_sequence", sa.Integer(), nullable=True),
        schema="characters",
    )
    op.add_column(
        "summary_revisions",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="characters",
    )
    op.execute("""
        UPDATE characters.summary_revisions AS summary
        SET checkpoint_sequence = message.sequence,
            is_active = NOT EXISTS (
                SELECT 1 FROM characters.summary_revisions AS newer
                WHERE newer.conversation_id = summary.conversation_id
                  AND newer.revision > summary.revision
            )
        FROM characters.messages AS message
        WHERE message.id = summary.checkpoint_message_id
        """)
    op.alter_column(
        "summary_revisions",
        "checkpoint_sequence",
        nullable=False,
        schema="characters",
    )
    op.alter_column(
        "summary_revisions", "is_active", server_default=None, schema="characters"
    )
    op.drop_index(
        "ix_summary_conversation_revision",
        table_name="summary_revisions",
        schema="characters",
    )
    op.drop_constraint(
        "uq_summary_checkpoint",
        "summary_revisions",
        schema="characters",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_summary_revision",
        "summary_revisions",
        ["conversation_id", "revision"],
        schema="characters",
    )
    op.create_unique_constraint(
        "uq_summary_successor",
        "summary_revisions",
        ["predecessor_id"],
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

    op.drop_constraint(
        "fk_conversation_selected_leaf",
        "conversations",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_column("conversations", "selected_leaf_id", schema="characters")
    op.drop_constraint(
        "ck_message_graph_shape", "messages", schema="characters", type_="check"
    )
    op.drop_constraint(
        "ck_message_role", "messages", schema="characters", type_="check"
    )
    op.drop_constraint(
        "fk_message_parent", "messages", schema="characters", type_="foreignkey"
    )
    op.drop_column("messages", "response_provenance", schema="characters")
    op.drop_column("messages", "parent_id", schema="characters")
