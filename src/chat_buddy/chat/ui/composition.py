"""Dependency composition for the Chat area."""

import streamlit as st

from chat_buddy.chat.application.config import ContextBuilderConfig, MemoryConfig
from chat_buddy.chat.application.context_builder import DefaultContextBuilder
from chat_buddy.chat.application.llm_summarizer import LLMSummarizer
from chat_buddy.chat.application.service import (
    ChatService,
    ConversationService,
    MemoryService,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.db import ChatSessionLocal
from chat_buddy.chat.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
)
from chat_buddy.chat.infrastructure.llm import build_provider_runtime
from chat_buddy.chat.infrastructure.tokenization import MistralTokenCounter


@st.cache_resource
def build_services() -> tuple[ChatService, ConversationService]:
    """Create the application services used by the Chat page."""

    session = ChatSessionLocal()
    conversation_repository = ConversationRepository(session)
    memory_repository = MemoryRepository(session)

    provider_runtime = build_provider_runtime()
    gateway = provider_runtime.legacy_gateway
    memory_service = MemoryService(
        repository=memory_repository,
        llm_gateway=gateway,
        config=MemoryConfig(
            extraction_interval=settings.MEMORY_EXTRACTION_INTERVAL,
        ),
    )
    conversation_service = ConversationService(
        repository=conversation_repository,
    )

    chat_service = ChatService(
        conversation_service=conversation_service,
        memory_service=memory_service,
        llm_gateway=gateway,
        context_builder=DefaultContextBuilder(
            token_counter=MistralTokenCounter(),
            summarizer=LLMSummarizer(gateway=gateway),
            config=ContextBuilderConfig(
                model_context_window=settings.MODEL_CONTEXT_WINDOW,
                prompt_overhead_tokens=settings.PROMPT_OVERHEAD_TOKENS,
                summary_trigger_ratio=settings.SUMMARY_TRIGGER_RATIO,
            ),
        ),
    )

    return chat_service, conversation_service
