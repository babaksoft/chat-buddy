"""
Minimal Streamlit UI for Chat Buddy.

Vertical slice:

Streamlit
    -> ChatService
    -> Ollama
    -> PostgreSQL
"""

from uuid import UUID

import streamlit as st

from chat_buddy.application.chat_service import ChatService
from chat_buddy.application.schemas import ChatRequest
from chat_buddy.infrastructure.config.logging import configure_logging
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
)
from chat_buddy.infrastructure.db.session import SessionLocal
from chat_buddy.infrastructure.llm.ollama_gateway import (
    OllamaGateway,
)

configure_logging()


def build_chat_service() -> ChatService:
    """
    Create application services.

    Returns:
        Configured chat service instance.
    """

    session = SessionLocal()

    repository = ConversationRepository(
        session=session,
    )

    gateway = OllamaGateway()

    return ChatService(
        repository=repository,
        llm_gateway=gateway,
    )


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

    service = build_chat_service()

    conversation_id = st.session_state.conversation_id

    if conversation_id is not None:
        render_conversation(
            service=service,
            conversation_id=conversation_id,
        )

    prompt = st.chat_input(
        "Send a message...",
    )

    if prompt:
        response = service.chat(
            ChatRequest(
                conversation_id=conversation_id,
                message=prompt,
            )
        )

        st.session_state.conversation_id = response.conversation_id

        st.rerun()


if __name__ == "__main__":
    main()
