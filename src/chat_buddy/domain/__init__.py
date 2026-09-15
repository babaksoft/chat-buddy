"""
Application-wide data classes and protocols.
"""

from chat_buddy.domain.chat import ChatMessage, ChatRole
from chat_buddy.domain.context_builder import ContextBuilder
from chat_buddy.domain.exceptions import ContextWindowExceededError
from chat_buddy.domain.extracted_memory import ExtractedMemory
from chat_buddy.domain.llm_gateway import LLMGateway
from chat_buddy.domain.repositories import (
    ConversationRecord,
    ConversationRepository,
    MemoryRecord,
    MemoryRepository,
    MessageRecord,
)
from chat_buddy.domain.summarizer import Summarizer
from chat_buddy.domain.tokenizer import TokenCounter, TokenUsage

__all__ = [
    "ChatMessage",
    "ChatRole",
    "ContextBuilder",
    "ContextWindowExceededError",
    "ConversationRecord",
    "ConversationRepository",
    "ExtractedMemory",
    "LLMGateway",
    "MemoryRecord",
    "MemoryRepository",
    "MessageRecord",
    "Summarizer",
    "TokenCounter",
    "TokenUsage",
]
