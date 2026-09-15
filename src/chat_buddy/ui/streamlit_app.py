"""
Streamlit application shell and service composition for Chat Buddy.
"""

import streamlit as st

from chat_buddy.application.config import ContextBuilderConfig, MemoryConfig
from chat_buddy.application.context_builder import DefaultContextBuilder
from chat_buddy.application.llm_summarizer import LLMSummarizer
from chat_buddy.application.service import (
    ChatService,
    ConversationService,
    MemoryService,
)
from chat_buddy.characters.ui import render as render_characters
from chat_buddy.infrastructure.config import settings
from chat_buddy.infrastructure.config.logging import configure_logging
from chat_buddy.infrastructure.db import SessionLocal
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
)
from chat_buddy.infrastructure.llm import OllamaGateway
from chat_buddy.infrastructure.tokenization import MistralTokenCounter
from chat_buddy.ui.pages import chat

configure_logging()


@st.cache_resource
def build_services() -> tuple[ChatService, ConversationService]:
    """
    Create application services.

    Returns:
        Configured instances of chat and conversation services.
    """

    session = SessionLocal()
    conversation_repository = ConversationRepository(session)
    memory_repository = MemoryRepository(session)

    gateway = OllamaGateway()
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


def main() -> None:
    """Configure the shared shell and render the selected application area."""

    st.set_page_config(
        page_title="Chat Buddy",
        page_icon="💬",
    )

    def chat_page() -> None:
        chat.render(service_factory=build_services)

    page = st.navigation(
        [
            st.Page(chat_page, title="Chat", icon="💬", default=True),
            st.Page(
                render_characters,
                title="Characters",
                icon="👥",
                url_path="characters",
            ),
        ],
        position="sidebar",
    )
    page.run()


if __name__ == "__main__":
    main()
