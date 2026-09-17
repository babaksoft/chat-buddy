"""Existing chat experience, independent of application navigation."""

from collections.abc import Callable
from uuid import UUID

import streamlit as st

from chat_buddy.chat.application.schemas import ChatRequest
from chat_buddy.chat.application.service import ChatService, ConversationService
from chat_buddy.chat.domain import ConversationRecord
from chat_buddy.chat.ui.composition import build_services


def render_conversation_editor(
    conversation_service: ConversationService,
    conversation: ConversationRecord,
) -> None:
    input_key = f"chat_rename_{conversation.id}"

    col_input, col_save, col_cancel = st.columns([8, 1, 1])

    with col_input:
        new_title = st.text_input(
            label="Rename conversation",
            value=conversation.title or "",
            key=input_key,
            label_visibility="collapsed",
        )

    with col_save:
        if st.button("✔", key=f"chat_save_{conversation.id}"):
            normalized = new_title.strip()

            if not normalized:
                st.toast("Title cannot be empty.")
                return

            if normalized != (conversation.title or ""):
                conversation_service.rename_conversation(
                    conversation_id=conversation.id,
                    title=normalized,
                )

            st.session_state.chat_editing_conversation_id = None
            st.rerun()

    with col_cancel:
        if st.button("✖", key=f"chat_cancel_{conversation.id}"):
            st.session_state.chat_editing_conversation_id = None
            st.rerun()


def render_delete_confirm(
    conversation_service: ConversationService,
    conversation: ConversationRecord,
) -> None:
    col_prompt, col_confirm, col_cancel = st.columns([8, 1, 1])

    with col_prompt:
        st.caption(f"Delete '{conversation.title}'?")

    with col_confirm:
        if st.button("✔", key=f"chat_confirm_delete_{conversation.id}"):
            deleted = conversation_service.delete_conversation(
                conversation_id=conversation.id,
            )

            if not deleted:
                st.toast("Conversation not found.")
            elif st.session_state.get("chat_conversation_id") == conversation.id:
                st.session_state.chat_conversation_id = None

            st.session_state.chat_confirming_delete_conversation_id = None
            st.session_state.chat_editing_conversation_id = None
            st.rerun()

    with col_cancel:
        if st.button("✖", key=f"chat_cancel_delete_{conversation.id}"):
            st.session_state.chat_confirming_delete_conversation_id = None
            st.rerun()


def render_conversation_row(
    conversation_service: ConversationService,
    conversation: ConversationRecord,
) -> None:
    editing_id = st.session_state.get("chat_editing_conversation_id")
    confirming_delete_id = st.session_state.get(
        "chat_confirming_delete_conversation_id"
    )

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

    current_id = st.session_state.get("chat_conversation_id")
    is_selected = current_id == conversation.id

    title = conversation.title or "New Conversation"
    col_title, col_rename, col_delete = st.columns([8, 1, 1])
    with col_title:
        label = f"👉 {title}" if is_selected else title

        if (
            st.button(
                label,
                key=f"chat_select_{conversation.id}",
                width="stretch",
            )
            and not is_selected
        ):
            st.session_state.chat_conversation_id = conversation.id
            st.rerun()

    with col_rename:
        if st.button(
            "✏️", key=f"chat_rename_{conversation.id}", help="Rename conversation"
        ):
            st.session_state.chat_editing_conversation_id = conversation.id
            st.session_state.chat_confirming_delete_conversation_id = None
            st.rerun()

    with col_delete:
        if st.button(
            "🗑️", key=f"chat_delete_{conversation.id}", help="Delete conversation"
        ):
            st.session_state.chat_confirming_delete_conversation_id = conversation.id
            st.session_state.chat_editing_conversation_id = None
            st.rerun()


def render_sidebar(conversation_service: ConversationService) -> None:
    with st.sidebar:
        st.header("Conversations")

        if st.button("+ New Chat", key="chat_new", width="stretch"):
            st.session_state.chat_conversation_id = None
            st.session_state.chat_editing_conversation_id = None
            st.session_state.chat_confirming_delete_conversation_id = None

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


def render(
    service_factory: (
        Callable[[], tuple[ChatService, ConversationService]] | None
    ) = None,
) -> None:
    """Render Chat, creating its services only when this area is selected."""

    st.title("💬 Chat")

    if "chat_conversation_id" not in st.session_state:
        st.session_state.chat_conversation_id = None

    if service_factory is None:
        service_factory = build_services

    chat_service, conversation_service = service_factory()
    render_sidebar(conversation_service=conversation_service)

    conversation_id = st.session_state.chat_conversation_id
    if conversation_id is not None:
        render_conversation(
            service=conversation_service,
            conversation_id=conversation_id,
        )

    prompt = st.chat_input(
        "Send a message...",
        key="chat_message",
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

        st.session_state.chat_conversation_id = new_conversation_id

        st.rerun()
