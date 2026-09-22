"""Existing chat experience, independent of application navigation."""

from collections.abc import Callable
from uuid import UUID

import streamlit as st

from chat_buddy.chat.application.schemas import ChatRequest
from chat_buddy.chat.application.service import (
    ChatService,
    ConversationService,
    MemoryManagementService,
)
from chat_buddy.chat.domain import (
    ConversationRecord,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    GenerationParameter,
    ModelId,
    ProviderId,
    ProviderInvocationError,
)
from chat_buddy.chat.ui.composition import build_services
from chat_buddy.chat.ui.memory_page import render as render_memory


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

        if st.button(
            label,
            key=f"chat_select_{conversation.id}",
            width="stretch",
        ) and (not is_selected or st.session_state.get("chat_view") != "conversation"):
            st.session_state.chat_view = "conversation"
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

        if st.button("🧠 Memory", key="chat_memory", width="stretch"):
            st.session_state.chat_view = "memory"
            st.rerun()

        if st.button("+ New Chat", key="chat_new", width="stretch"):
            st.session_state.chat_view = "conversation"
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


def _optional_float(
    label: str, value: float | None, *, minimum: float, maximum: float, key: str
) -> float | None:
    """Render an optional floating-point generation setting.

    Args:
        label:
            User-visible input label.
        value:
            Currently requested value.
        minimum:
            Smallest accepted value.
        maximum:
            Largest accepted value.
        key:
            Stable Streamlit widget key.

    Returns:
        Requested value, or ``None`` to use the model default.
    """

    result = st.number_input(
        label,
        min_value=minimum,
        max_value=maximum,
        value=value,
        step=0.05,
        key=key,
        placeholder="Model default",
    )
    return float(result) if result is not None else None


def _optional_int(
    label: str, value: int | None, *, minimum: int, key: str
) -> int | None:
    """Render an optional integer generation setting.

    Args:
        label:
            User-visible input label.
        value:
            Currently requested value.
        minimum:
            Smallest accepted value.
        key:
            Stable Streamlit widget key.

    Returns:
        Requested value, or ``None`` to use the model default.
    """

    result = st.number_input(
        label,
        min_value=minimum,
        value=value,
        step=1,
        key=key,
        placeholder="Model default",
    )
    return int(result) if result is not None else None


def render_generation_selection(
    chat_service: ChatService,
    conversation_id: UUID | None,
) -> UUID | None:
    """Render and persist provider-neutral defaults for the next response.

    Args:
        chat_service:
            Chat application service exposing provider choices.
        conversation_id:
            Currently selected conversation, if any.

    Returns:
        Existing or newly created conversation identifier.
    """

    selection = chat_service.get_generation_selection(conversation_id)
    key_suffix = str(conversation_id or "new")
    provider_names = {str(item.id): item.display_name for item in selection.providers}
    provider_values = tuple(provider_names)
    selected_provider = st.selectbox(
        "Provider",
        provider_values,
        index=provider_values.index(str(selection.provider_id)),
        format_func=provider_names.__getitem__,
        key=f"chat_provider_{key_suffix}",
    )
    provider_id = ProviderId(selected_provider)
    available_models = tuple(
        item for item in selection.models if item.provider_id == provider_id
    )
    model_names = {str(item.id): item.display_name for item in available_models}
    model_values = tuple(model_names)
    persisted_model = str(selection.model_id)
    model_index = (
        model_values.index(persisted_model) if persisted_model in model_values else 0
    )
    selected_model = st.selectbox(
        "Model",
        model_values,
        index=model_index,
        format_func=model_names.__getitem__,
        key=f"chat_model_{key_suffix}_{provider_id}",
    )
    model_id = ModelId(selected_model)
    model = next(item for item in available_models if item.id == model_id)
    provider = next(item for item in selection.providers if item.id == provider_id)
    if provider.usage_notice is not None:
        st.caption(provider.usage_notice)
    current = selection.configuration
    with st.expander("Generation settings"):
        temperature = (
            _optional_float(
                "Temperature",
                current.temperature,
                minimum=0.0,
                maximum=2.0,
                key=f"chat_temperature_{key_suffix}_{provider_id}_{model_id}",
            )
            if GenerationParameter.TEMPERATURE in model.supported_generation_parameters
            else None
        )
        top_p = (
            _optional_float(
                "Top P",
                current.top_p,
                minimum=0.01,
                maximum=1.0,
                key=f"chat_top_p_{key_suffix}_{provider_id}_{model_id}",
            )
            if GenerationParameter.TOP_P in model.supported_generation_parameters
            else None
        )
        max_output_tokens = (
            _optional_int(
                "Maximum output tokens",
                current.max_output_tokens,
                minimum=1,
                key=f"chat_max_tokens_{key_suffix}_{provider_id}_{model_id}",
            )
            if GenerationParameter.MAX_OUTPUT_TOKENS
            in model.supported_generation_parameters
            else None
        )
        seed = (
            _optional_int(
                "Seed",
                current.seed,
                minimum=0,
                key=f"chat_seed_{key_suffix}_{provider_id}_{model_id}",
            )
            if GenerationParameter.SEED in model.supported_generation_parameters
            else None
        )
    configuration = GenerationConfiguration(
        temperature=temperature,
        top_p=top_p,
        max_output_tokens=max_output_tokens,
        seed=seed,
    )
    if (
        provider_id != selection.provider_id
        or model_id != selection.model_id
        or configuration != selection.configuration
    ):
        conversation_id = chat_service.update_generation_selection(
            conversation_id,
            provider_id,
            model_id,
            configuration,
        )
        st.session_state.chat_conversation_id = conversation_id
        st.rerun()

    return conversation_id


def _attempt_message(attempt: GenerationAttemptRecord) -> str:
    """Build safe user-facing copy for an incomplete attempt.

    Args:
        attempt:
            Failed or interrupted generation attempt.

    Returns:
        Status copy suitable for the recovery panel.
    """

    if attempt.status is GenerationAttemptStatus.FAILED:
        return (
            attempt.error_detail
            or "The response provider could not complete the request."
        )

    return "Response generation was interrupted before it completed."


def render_recovery(
    chat_service: ChatService,
    conversation_id: UUID,
) -> None:
    """Render incomplete attempts separately from completed message history.

    Args:
        chat_service:
            Chat application service used for recovery operations.
        conversation_id:
            Conversation whose recoverable attempts to render.
    """

    attempts = chat_service.get_recoverable_generation_attempts(conversation_id)
    for attempt in attempts:
        with st.container(border=True):
            st.warning(_attempt_message(attempt))
            if attempt.partial_content:
                st.caption("Incomplete response")
                st.markdown(attempt.partial_content)
            if st.button("Retry", key=f"chat_retry_{attempt.id}"):
                with st.chat_message("assistant"):
                    _, response_generator = chat_service.stream_retry(attempt.id)
                    try:
                        st.write_stream(response_generator)
                    except ProviderInvocationError:
                        st.rerun()

                st.rerun()


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
        Callable[
            [],
            tuple[ChatService, ConversationService, MemoryManagementService],
        ]
        | None
    ) = None,
) -> None:
    """Render Chat, creating its services only when this area is selected."""

    if "chat_conversation_id" not in st.session_state:
        st.session_state.chat_conversation_id = None
    if "chat_view" not in st.session_state:
        st.session_state.chat_view = "conversation"

    if service_factory is None:
        service_factory = build_services

    chat_service, conversation_service, memory_management_service = service_factory()
    render_sidebar(conversation_service=conversation_service)

    if st.session_state.chat_view == "memory":
        render_memory(memory_management_service)
        return

    st.title("💬 Chat")

    conversation_id = st.session_state.chat_conversation_id
    conversation_id = render_generation_selection(
        chat_service=chat_service,
        conversation_id=conversation_id,
    )
    if conversation_id is not None:
        render_conversation(
            service=conversation_service,
            conversation_id=conversation_id,
        )
        render_recovery(
            chat_service=chat_service,
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
            st.session_state.chat_conversation_id = new_conversation_id
            try:
                st.write_stream(response_generator)
            except ProviderInvocationError:
                st.rerun()

        st.rerun()
