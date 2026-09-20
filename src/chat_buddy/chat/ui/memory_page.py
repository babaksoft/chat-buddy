"""Chat-owned memory inspection and management view."""

from datetime import datetime
from uuid import UUID

import streamlit as st

from chat_buddy.chat.application.schemas import (
    ManagedMemory,
    MemoryManagementOutcome,
    MemoryManagementResult,
)
from chat_buddy.chat.application.service import MemoryManagementService
from chat_buddy.chat.domain import MemoryLifecycle, MemoryOriginKind


def _format_timestamp(value: datetime) -> str:
    """Format an application timestamp for compact display.

    Args:
        value:
            Timezone-aware timestamp to format.

    Returns:
        Human-readable timestamp retaining its timezone.
    """

    return value.strftime("%Y-%m-%d %H:%M:%S %Z")


def _clear_action_state(memory_id: UUID) -> None:
    """Clear transient controls for one memory.

    Args:
        memory_id:
            Logical memory whose controls should close.
    """

    if st.session_state.get("chat_editing_memory_id") == memory_id:
        st.session_state.chat_editing_memory_id = None
    if st.session_state.get("chat_deleting_memory_id") == memory_id:
        st.session_state.chat_deleting_memory_id = None


def _complete_action(
    result: MemoryManagementResult,
    *,
    memory_id: UUID,
    success_message: str,
) -> None:
    """Present an application action result and refresh when safe.

    Args:
        result:
            Persistence-neutral result returned by the application service.
        memory_id:
            Logical memory targeted by the action.
        success_message:
            Toast copy for a successful or already-applied action.
    """

    if result.outcome in {
        MemoryManagementOutcome.UPDATED,
        MemoryManagementOutcome.UNCHANGED,
    }:
        _clear_action_state(memory_id)
        st.toast(success_message)
        st.rerun()
    if result.outcome is MemoryManagementOutcome.NOT_FOUND:
        _clear_action_state(memory_id)
        st.warning("This memory no longer exists. Refreshing the list.")
        st.rerun()

    st.warning("This memory changed in another session. Review it and try again.")


def _render_provenance(memory: ManagedMemory) -> None:
    """Render origin and optional source-turn details.

    Args:
        memory:
            Application read model to inspect.
    """

    provenance = memory.provenance
    if provenance.kind is MemoryOriginKind.USER_CORRECTION:
        st.caption("Origin: corrected by you")
        if provenance.corrected_at is not None:
            st.caption(f"Corrected: {_format_timestamp(provenance.corrected_at)}")
        return

    st.caption("Origin: extracted from a completed Chat turn")
    source = provenance.source
    if not provenance.source_available or source is None:
        st.info("The source conversation or turn is no longer available.")
        return

    with st.expander("Source turn"):
        st.caption(
            f"Conversation: {source.conversation_title or 'Untitled conversation'}"
        )
        st.markdown(f"**You:** {source.user_message_content}")
        st.markdown(f"**Assistant:** {source.assistant_message_content}")


def _render_correction(
    service: MemoryManagementService,
    memory: ManagedMemory,
) -> None:
    """Render correction inputs for one active memory.

    Args:
        service:
            Application service used to persist a correction.
        memory:
            Current inspected memory revision.
    """

    subject = st.text_input(
        "Subject",
        value=memory.subject,
        key=f"chat_memory_subject_{memory.id}",
    )
    content = st.text_area(
        "Memory",
        value=memory.content,
        key=f"chat_memory_content_{memory.id}",
    )
    save_column, cancel_column = st.columns(2)
    with save_column:
        if st.button("Save correction", key=f"chat_memory_save_{memory.id}"):
            try:
                result = service.correct_memory(
                    memory.id,
                    expected_revision_id=memory.revision_id,
                    subject=subject,
                    content=content,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                _complete_action(
                    result,
                    memory_id=memory.id,
                    success_message="Memory corrected.",
                )
    with cancel_column:
        if st.button("Cancel", key=f"chat_memory_cancel_edit_{memory.id}"):
            st.session_state.chat_editing_memory_id = None
            st.rerun()


def _render_delete_confirmation(
    service: MemoryManagementService,
    memory: ManagedMemory,
) -> None:
    """Require explicit confirmation before permanently deleting a memory.

    Args:
        service:
            Application service used for hard deletion.
        memory:
            Current inspected memory revision.
    """

    st.warning(
        "Permanently delete this memory and its provenance? "
        "This action is irreversible."
    )
    confirm_column, cancel_column = st.columns(2)
    with confirm_column:
        if st.button(
            "Permanently delete",
            key=f"chat_memory_confirm_delete_{memory.id}",
            type="primary",
        ):
            result = service.delete_memory(
                memory.id,
                expected_revision_id=memory.revision_id,
            )
            _complete_action(
                result,
                memory_id=memory.id,
                success_message="Memory permanently deleted.",
            )
    with cancel_column:
        if st.button("Cancel", key=f"chat_memory_cancel_delete_{memory.id}"):
            st.session_state.chat_deleting_memory_id = None
            st.rerun()


def _render_actions(
    service: MemoryManagementService,
    memory: ManagedMemory,
) -> None:
    """Render correction and lifecycle controls for one memory.

    Args:
        service:
            Application service used for all mutations.
        memory:
            Current inspected memory revision.
    """

    if st.session_state.get("chat_editing_memory_id") == memory.id:
        _render_correction(service, memory)
        return
    if st.session_state.get("chat_deleting_memory_id") == memory.id:
        _render_delete_confirmation(service, memory)
        return

    action_columns = st.columns(3)
    with action_columns[0]:
        if st.button(
            "Correct",
            key=f"chat_memory_edit_{memory.id}",
            disabled=memory.lifecycle is not MemoryLifecycle.ACTIVE,
        ):
            st.session_state.chat_editing_memory_id = memory.id
            st.session_state.chat_deleting_memory_id = None
            st.rerun()
    with action_columns[1]:
        if memory.lifecycle is MemoryLifecycle.ACTIVE:
            if st.button("Exclude", key=f"chat_memory_exclude_{memory.id}"):
                result = service.exclude_memory(
                    memory.id,
                    expected_revision_id=memory.revision_id,
                )
                _complete_action(
                    result,
                    memory_id=memory.id,
                    success_message="Memory excluded from future responses.",
                )
        elif st.button("Reactivate", key=f"chat_memory_reactivate_{memory.id}"):
            result = service.reactivate_memory(
                memory.id,
                expected_revision_id=memory.revision_id,
            )
            _complete_action(
                result,
                memory_id=memory.id,
                success_message="Memory restored for future responses.",
            )
    with action_columns[2]:
        if st.button("Delete", key=f"chat_memory_delete_{memory.id}"):
            st.session_state.chat_deleting_memory_id = memory.id
            st.session_state.chat_editing_memory_id = None
            st.rerun()


def _render_memory(
    service: MemoryManagementService,
    memory: ManagedMemory,
) -> None:
    """Render one compact memory inspection card.

    Args:
        service:
            Application service used for memory actions.
        memory:
            Persistence-neutral memory to render.
    """

    with st.container(border=True):
        st.subheader(memory.subject)
        st.markdown(memory.content)
        st.caption(f"State: {memory.lifecycle.value}")
        _render_provenance(memory)
        st.caption(
            f"Created: {_format_timestamp(memory.created_at)} · "
            f"Updated: {_format_timestamp(memory.updated_at)}"
        )
        _render_actions(service, memory)


def render(service: MemoryManagementService) -> None:
    """Render Chat memory inspection without requiring a conversation.

    Args:
        service:
            Chat application service for memory inspection and management.
    """

    st.title("🧠 Memory")
    st.caption("Review and control what Chat can use in future responses.")
    memories = service.list_memories()
    if not memories:
        st.info("No Chat memories have been saved yet.")
        return

    for memory in memories:
        _render_memory(service, memory)
