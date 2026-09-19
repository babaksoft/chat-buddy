"""Domain models and contracts for the Chat area."""

from chat_buddy.chat.domain.chat import ChatMessage, ChatRole
from chat_buddy.chat.domain.context import (
    CompletedTurn,
    CompletedTurnMemoryExtraction,
    ContextAssemblyResult,
    ContextBudgeter,
    ContextEligibility,
    ContextInputs,
    RollingSummarizer,
)
from chat_buddy.chat.domain.context_builder import ContextBuilder
from chat_buddy.chat.domain.exceptions import (
    ContextWindowExceededError,
    InvalidGenerationAttemptTransitionError,
    InvalidGenerationConfigurationError,
    ProviderInvocationError,
    UnknownModelError,
    UnknownProviderError,
)
from chat_buddy.chat.domain.extracted_memory import ExtractedMemory
from chat_buddy.chat.domain.gateways import (
    MemoryCandidateExtractor,
    MemoryExtractor,
    ResponseGatewayResolver,
    ResponseGenerator,
    RollingSummaryGenerator,
    SummaryGenerator,
    TitleGenerator,
)
from chat_buddy.chat.domain.generation_attempt import (
    GenerationAttemptRecord,
    GenerationAttemptStatus,
)
from chat_buddy.chat.domain.llm_gateway import LLMGateway
from chat_buddy.chat.domain.memory import (
    ChatMemory,
    MemoryCandidate,
    MemoryDeletionResult,
    MemoryExtractionOutcome,
    MemoryExtractionReceipt,
    MemoryLifecycle,
    MemoryOrigin,
    MemoryOriginKind,
    normalize_memory_subject,
    normalize_memory_text,
)
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
    ChatMemoryRepository,
    ConversationRecord,
    ConversationRepository,
    MessageRecord,
    SummaryRepository,
)
from chat_buddy.chat.domain.summarizer import Summarizer
from chat_buddy.chat.domain.summary import (
    ConversationSummary,
    SummaryLifecycle,
    SummaryProvenance,
)
from chat_buddy.chat.domain.tokenizer import TokenCounter, TokenUsage

__all__ = [
    "ChatMemory",
    "ChatMemoryRepository",
    "ChatMessage",
    "ChatRole",
    "CompletedTurn",
    "CompletedTurnMemoryExtraction",
    "ContextAssemblyResult",
    "ContextBudgeter",
    "ContextBuilder",
    "ContextEligibility",
    "ContextInputs",
    "ContextWindowExceededError",
    "ConversationRecord",
    "ConversationRepository",
    "ConversationSummary",
    "ExtractedMemory",
    "GenerationAttemptRecord",
    "GenerationAttemptStatus",
    "GenerationConfiguration",
    "GenerationParameter",
    "InvalidGenerationAttemptTransitionError",
    "InvalidGenerationConfigurationError",
    "LLMGateway",
    "MemoryCandidate",
    "MemoryCandidateExtractor",
    "MemoryDeletionResult",
    "MemoryExtractionOutcome",
    "MemoryExtractionReceipt",
    "MemoryExtractor",
    "MemoryLifecycle",
    "MemoryOrigin",
    "MemoryOriginKind",
    "MessageRecord",
    "ModelDescriptor",
    "ModelId",
    "ProviderDescriptor",
    "ProviderId",
    "ProviderInvocationError",
    "ProviderRegistry",
    "ResponseGatewayResolver",
    "ResponseGenerator",
    "RollingSummarizer",
    "RollingSummaryGenerator",
    "Summarizer",
    "SummaryGenerator",
    "SummaryLifecycle",
    "SummaryProvenance",
    "SummaryRepository",
    "TitleGenerator",
    "TokenCounter",
    "TokenUsage",
    "UnknownModelError",
    "UnknownProviderError",
    "normalize_memory_subject",
    "normalize_memory_text",
]
