"""Domain models and contracts for the Chat area."""

from chat_buddy.chat.domain.chat import ChatMessage, ChatRole
from chat_buddy.chat.domain.context_builder import ContextBuilder
from chat_buddy.chat.domain.exceptions import (
    ContextWindowExceededError,
    InvalidGenerationAttemptTransitionError,
    InvalidGenerationConfigurationError,
)
from chat_buddy.chat.domain.extracted_memory import ExtractedMemory
from chat_buddy.chat.domain.gateways import (
    MemoryExtractor,
    ResponseGatewayResolver,
    ResponseGenerator,
    SummaryGenerator,
    TitleGenerator,
)
from chat_buddy.chat.domain.generation_attempt import (
    GenerationAttempt,
    GenerationAttemptStatus,
)
from chat_buddy.chat.domain.llm_gateway import LLMGateway
from chat_buddy.chat.domain.providers import (
    GenerationConfiguration,
    GenerationParameter,
    ModelDescriptor,
    ModelId,
    ProviderDescriptor,
    ProviderId,
    ProviderRegistry,
)
from chat_buddy.chat.domain.repositories import (
    ConversationRecord,
    ConversationRepository,
    MemoryRecord,
    MemoryRepository,
    MessageRecord,
)
from chat_buddy.chat.domain.summarizer import Summarizer
from chat_buddy.chat.domain.tokenizer import TokenCounter, TokenUsage

__all__ = [
    "ChatMessage",
    "ChatRole",
    "ContextBuilder",
    "ContextWindowExceededError",
    "ConversationRecord",
    "ConversationRepository",
    "ExtractedMemory",
    "GenerationAttempt",
    "GenerationAttemptStatus",
    "GenerationConfiguration",
    "GenerationParameter",
    "InvalidGenerationAttemptTransitionError",
    "InvalidGenerationConfigurationError",
    "LLMGateway",
    "MemoryExtractor",
    "MemoryRecord",
    "MemoryRepository",
    "MessageRecord",
    "ModelDescriptor",
    "ModelId",
    "ProviderDescriptor",
    "ProviderId",
    "ProviderRegistry",
    "ResponseGatewayResolver",
    "ResponseGenerator",
    "Summarizer",
    "SummaryGenerator",
    "TitleGenerator",
    "TokenCounter",
    "TokenUsage",
]
