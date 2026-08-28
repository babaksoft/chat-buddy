"""
Streamlit UI for Chat Buddy.
"""

from uuid import UUID

import streamlit as st

from chat_buddy.application.context_builder import DefaultContextBuilder
from chat_buddy.application.schemas import ChatRequest, ConversationEntry
from chat_buddy.application.service import (
    ChatService,
    ConversationService,
    MemoryService,
)
from chat_buddy.infrastructure.config.logging import configure_logging
from chat_buddy.infrastructure.db import SessionLocal
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
    MemoryRepository,
)
from chat_buddy.infrastructure.llm import OllamaGateway
from chat_buddy.infrastructure.tokenization import MistralTokenCounter

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
        ),
    )

    return chat_service, conversation_service


def render_conversation_editor(
    conversation_service: ConversationService,
    conversation: ConversationEntry,
) -> None:
    input_key = f"rename_{conversation.id}"

    col_input, col_save, col_cancel = st.columns([8, 1, 1])

    with col_input:
        new_title = st.text_input(
            label="Rename conversation",
            value=conversation.title or "",
            key=input_key,
            label_visibility="collapsed",
        )

    with col_save:
        if st.button("✔", key=f"save_{conversation.id}"):
            normalized = new_title.strip()

            if not normalized:
                st.toast("Title cannot be empty.")
                return

            if normalized != (conversation.title or ""):
                conversation_service.rename_conversation(
                    conversation_id=conversation.id,
                    title=normalized,
                )

            st.session_state.editing_conversation_id = None
            st.rerun()

    with col_cancel:
        if st.button("✖", key=f"cancel_{conversation.id}"):
            st.session_state.editing_conversation_id = None
            st.rerun()


def render_delete_confirm(
    conversation_service: ConversationService,
    conversation: ConversationEntry,
) -> None:
    col_prompt, col_confirm, col_cancel = st.columns([8, 1, 1])

    with col_prompt:
        st.caption(f"Delete '{conversation.title}'?")

    with col_confirm:
        if st.button("✔", key=f"confirm_delete_{conversation.id}"):
            deleted = conversation_service.delete_conversation(
                conversation_id=conversation.id,
            )

            if not deleted:
                st.toast("Conversation not found.")
            elif st.session_state.get("conversation_id") == conversation.id:
                st.session_state.conversation_id = None

            st.session_state.confirming_delete_conversation_id = None
            st.session_state.editing_conversation_id = None
            st.rerun()

    with col_cancel:
        if st.button("✖", key=f"cancel_delete_{conversation.id}"):
            st.session_state.confirming_delete_conversation_id = None
            st.rerun()


def render_conversation_row(
    conversation_service: ConversationService,
    conversation: ConversationEntry,
) -> None:
    editing_id = st.session_state.get("editing_conversation_id")
    confirming_delete_id = st.session_state.get("confirming_delete_conversation_id")

    if editing_id == conversation.id:
        render_conversation_editor(
            conversation_service=conversation_service,
            conversation=conversation,
        )
        return

    if confirming_delete_id == conversation.id:
        render_delete_confirm(
            conversation_service=conversation_service,
            conversation=conversation,
        )
        return

    current_id = st.session_state.get("conversation_id")
    is_selected = current_id == conversation.id

    title = conversation.title or "New Conversation"
    col_title, col_rename, col_delete = st.columns([8, 1, 1])
    with col_title:
        label = f"👉 {title}" if is_selected else title

        if st.button(
            label,
            key=f"select_{conversation.id}",
            width="stretch",
        ):
            if not is_selected:
                st.session_state.conversation_id = conversation.id
                st.rerun()

    with col_rename:
        if st.button("✏️", key=f"rename_{conversation.id}", help="Rename conversation"):
            st.session_state.editing_conversation_id = conversation.id
            st.session_state.confirming_delete_conversation_id = None
            st.rerun()

    with col_delete:
        if st.button("🗑️", key=f"delete_{conversation.id}", help="Delete conversation"):
            st.session_state.confirming_delete_conversation_id = conversation.id
            st.session_state.editing_conversation_id = None
            st.rerun()


def render_sidebar(conversation_service: ConversationService) -> None:
    with st.sidebar:
        st.header("Conversations")

        if st.button("+ New Chat", width="stretch"):
            st.session_state.conversation_id = None
            st.session_state.editing_conversation_id = None
            st.session_state.confirming_delete_conversation_id = None

            st.rerun()

        conversations = conversation_service.get_conversations()

        if not conversations:
            st.caption("No conversations yet.")
            return

        st.divider()

        for conversation in conversations:
            render_conversation_row(
                conversation_service=conversation_service,
                conversation=conversation,
            )


def render_conversation(
    service: ConversationService,
    conversation_id: UUID,
) -> None:
    """
    Render all messages in a conversation.

    Args:
        service:
            Conversation service.

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
            service=conversation_service,
            conversation_id=conversation_id,
        )

    prompt = st.chat_input(
        "Send a message...",
    )

    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            new_conversation_id, response_generator = chat_service.stream_chat(
                ChatRequest(
                    conversation_id=conversation_id,
                    message=prompt,
                )
            )
            st.write_stream(response_generator)

        st.session_state.conversation_id = new_conversation_id

        st.rerun()


if __name__ == "__main__":
    main()
