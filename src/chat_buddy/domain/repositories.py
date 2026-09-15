"""Compatibility exports for Chat repository contracts and records."""

from chat_buddy.chat.domain.repositories import (
    ConversationRecord,
    ConversationRepository,
    MemoryRecord,
    MemoryRepository,
    MessageRecord,
)

__all__ = [
    "ConversationRecord",
    "ConversationRepository",
    "MemoryRecord",
    "MemoryRepository",
    "MessageRecord",
]
