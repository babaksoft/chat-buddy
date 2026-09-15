"""Chat-owned persistence adapters and session wiring."""

from chat_buddy.chat.infrastructure.db.base import ChatBase
from chat_buddy.chat.infrastructure.db.session import ChatSessionLocal, chat_engine

__all__ = [
    "ChatBase",
    "ChatSessionLocal",
    "chat_engine",
]
