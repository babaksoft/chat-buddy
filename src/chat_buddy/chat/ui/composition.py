"""Dependency composition for the Chat area."""

import streamlit as st

from chat_buddy.chat.application.config import ContextBuilderConfig
from chat_buddy.chat.application.context_builder import DefaultContextBuilder
from chat_buddy.chat.application.llm_summarizer import LLMSummarizer
from chat_buddy.chat.application.service import (
    ChatService,
    ConversationService,
    MemoryExtractionService,
    MemoryManagementService,
    MemoryService,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.db import ChatSessionLocal
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
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
    memory_repository = MemoryRepository(session)

    provider_runtime = build_provider_runtime()
    utility_gateway = provider_runtime.utility_gateway
    memory_service = MemoryService(
        repository=memory_repository,
    )
    memory_extraction_service = MemoryExtractionService(
        repository=memory_repository,
        extractor=utility_gateway,
    )
    conversation_service = ConversationService(
        repository=conversation_repository,
    )
    memory_management_service = MemoryManagementService(
        memory_repository=memory_repository,
        conversation_repository=conversation_repository,
    )

    chat_service = ChatService(
        conversation_service=conversation_service,
        memory_service=memory_service,
        memory_extraction_service=memory_extraction_service,
        provider_registry=provider_runtime.registry,
        response_gateway_resolver=provider_runtime.response_gateway_resolver,
        title_generator=utility_gateway,
        context_builder=DefaultContextBuilder(
            summarizer=LLMSummarizer(gateway=utility_gateway),
            config=ContextBuilderConfig(
                prompt_overhead_tokens=settings.PROMPT_OVERHEAD_TOKENS,
                summary_trigger_ratio=settings.SUMMARY_TRIGGER_RATIO,
            ),
        ),
    )

    return chat_service, conversation_service, memory_management_service
