"""Compatibility export for the Chat conversation repository."""

from chat_buddy.chat.infrastructure.db.repositories.conversation_repository import (
    ConversationRepository,
)

__all__ = ["ConversationRepository"]
