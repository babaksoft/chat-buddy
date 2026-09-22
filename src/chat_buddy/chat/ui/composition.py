"""Dependency composition for the Chat area."""

import streamlit as st

from chat_buddy.chat.application.config import ContextBudgetConfig, RollingSummaryConfig
from chat_buddy.chat.application.context_builder import (
    ContextAssemblyService,
    DefaultContextBudgeter,
    DefaultContextEligibility,
)
from chat_buddy.chat.application.llm_summarizer import LLMSummarizer
from chat_buddy.chat.application.service import (
    ChatService,
    ConversationService,
    GenerationAttemptService,
    MemoryExtractionService,
    MemoryManagementService,
    RollingSummaryService,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.db import ChatSessionLocal
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    GenerationAttemptRepository,
    MemoryRepository,
    SummaryRepository,
)
from chat_buddy.chat.infrastructure.llm import build_provider_runtime


@st.cache_resource
def build_services() -> tuple[
    ChatService,
    ConversationService,
    MemoryManagementService,
]:
    """Create the application services used by the Chat page."""

    session = ChatSessionLocal()
    conversation_repository = ConversationRepository(session)
    generation_attempt_repository = GenerationAttemptRepository(session)
    memory_repository = MemoryRepository(session)
    summary_repository = SummaryRepository(session)

    provider_runtime = build_provider_runtime()
    memory_extraction_service = MemoryExtractionService(
        repository=memory_repository,
        extractor=provider_runtime.memory_candidate_extractor,
    )
    conversation_service = ConversationService(
        repository=conversation_repository,
    )
    generation_attempt_service = GenerationAttemptService(
        repository=generation_attempt_repository,
    )
    memory_management_service = MemoryManagementService(
        memory_repository=memory_repository,
        conversation_repository=conversation_repository,
    )
    rolling_summary_service = RollingSummaryService(
        repository=summary_repository,
        generator=LLMSummarizer(gateway=provider_runtime.summary_generator),
        config=RollingSummaryConfig(
            prompt_overhead_tokens=settings.PROMPT_OVERHEAD_TOKENS,
            summary_trigger_ratio=settings.SUMMARY_TRIGGER_RATIO,
            minimum_recent_turns=settings.MINIMUM_RECENT_TURNS,
        ),
    )
    context_assembler = ContextAssemblyService(
        eligibility=DefaultContextEligibility(
            memory_repository=memory_repository,
            summary_repository=summary_repository,
        ),
        budgeter=DefaultContextBudgeter(
            ContextBudgetConfig(
                prompt_overhead_tokens=settings.PROMPT_OVERHEAD_TOKENS,
                minimum_recent_turns=settings.MINIMUM_RECENT_TURNS,
            )
        ),
        rolling_summarizer=rolling_summary_service,
    )

    chat_service = ChatService(
        conversation_service=conversation_service,
        generation_attempt_service=generation_attempt_service,
        memory_extraction_service=memory_extraction_service,
        provider_registry=provider_runtime.registry,
        response_gateway_resolver=provider_runtime.response_gateway_resolver,
        title_generator=provider_runtime.title_generator,
        context_assembler=context_assembler,
    )

    return chat_service, conversation_service, memory_management_service
