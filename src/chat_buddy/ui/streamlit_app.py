"""
Streamlit UI for Chat Buddy.
"""

from uuid import UUID

import streamlit as st

from chat_buddy.application.chat_service import ChatService
from chat_buddy.application.context_builder import DefaultContextBuilder
from chat_buddy.application.conversation_service import ConversationService
from chat_buddy.application.schemas import ChatRequest
from chat_buddy.infrastructure.config.logging import configure_logging
from chat_buddy.infrastructure.db.repositories import ConversationRepository
from chat_buddy.infrastructure.db.session import SessionLocal
from chat_buddy.infrastructure.llm.ollama_gateway import OllamaGateway
from chat_buddy.infrastructure.tokenization.mistral_token_counter import (
    MistralTokenCounter,
)

configure_logging()


def build_services() -> tuple[ChatService, ConversationService]:
    """
    Create application services.

    Returns:
        Configured instances of chat and conversation services.
    """

    session = SessionLocal()
    repository = ConversationRepository(
        session=session,
    )

    gateway = OllamaGateway()

    chat_service = ChatService(
        repository=repository,
        llm_gateway=gateway,
        context_builder=DefaultContextBuilder(token_counter=MistralTokenCounter()),
    )
    conversation_service = ConversationService(repository=repository)

    return chat_service, conversation_service


def render_sidebar(conversation_service: ConversationService) -> None:
    """
    Render application sidebar that enables conversation management.

    Args:
        conversation_service:
            Conversation service.
    """

    with st.sidebar:
        st.header("Conversations")

        if st.button("+ New Chat"):
            conversation = conversation_service.new_conversation()

            st.session_state.conversation_id = conversation.id
            st.session_state.selected_conversation = conversation

            st.rerun()

        conversations = conversation_service.list_conversations()
        if conversations:
            selected = st.radio(
                "Existing conversations",
                options=conversations,
                index=None,
                key="selected_conversation",
                format_func=lambda c: (
                    c.title if c.title else f"Conversation {str(c.id)[:8]}"
                ),
            )

            if selected is not None and selected.id != st.session_state.conversation_id:
                st.session_state.conversation_id = selected.id
                st.rerun()


def render_conversation(
    service: ChatService,
    conversation_id: UUID,
) -> None:
    """
    Render all messages in a conversation.

    Args:
        service:
            Chat service.

        conversation_id:
            Conversation identifier.
    """

    messages = service.get_messages(
        conversation_id=conversation_id,
    )

    for message in messages:
        with st.chat_message(
            name=message.role.value,
        ):
            st.markdown(message.content)


def main() -> None:
    """
    Application entry point.
    """

    st.set_page_config(
        page_title="Chat Buddy",
        page_icon="💬",
    )
    st.title("💬 Chat Buddy")

    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = None

    chat_service, conversation_service = build_services()
    render_sidebar(conversation_service=conversation_service)

    conversation_id = st.session_state.conversation_id
    if conversation_id is not None:
        render_conversation(
            service=chat_service,
            conversation_id=conversation_id,
        )

    prompt = st.chat_input(
        "Send a message...",
    )

    if prompt:
        response = chat_service.chat(
            ChatRequest(
                conversation_id=conversation_id,
                message=prompt,
            )
        )

        st.session_state.conversation_id = response.conversation_id

        st.rerun()


if __name__ == "__main__":
    main()
