"""
SQLAlchemy ORM models for the chat_buddy application.

This module defines the database schema for conversations and messages,
using SQLAlchemy's declarative ORM. The models are designed for PostgreSQL
and use UUID primary keys, timezone-aware timestamps, and appropriate text
types for chat content.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Conversation(Base):
    """Represents a chat conversation.

    A conversation contains multiple messages and an optional running summary
    used for memory compression. Conversations are ordered by their
    `updated_at` timestamp, which is refreshed whenever a new message is added.

    Attributes:
        id (UUID): Primary key for the conversation.
        title (str): Human-readable title, usually derived from the first user message.
        created_at (datetime): Timestamp when the conversation was created.
        updated_at (datetime): Timestamp when the conversation was last updated.
        summary (str | None): Optional running summary of older messages.
        messages (list[Message]): Relationship to associated messages.
    """

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    title = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    summary = Column(String(1024), nullable=True)

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """Represents a single message within a conversation.

    Each message belongs to exactly one conversation and stores the role
    (e.g., 'user', 'assistant') and the message content.

    Attributes:
        id (UUID): Primary key for the message.
        conversation_id (UUID): Foreign key referencing the parent conversation.
        role (str): Role of the sender ('user', 'assistant', etc.).
        content (str): Full message text.
        created_at (datetime): Timestamp when the message was created.
        conversation (Conversation): Relationship back to the parent conversation.
    """

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    conversation = relationship("Conversation", back_populates="messages")
