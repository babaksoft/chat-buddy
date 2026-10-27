"""Continuity-scoped Storyline memory and conflict controls."""

from typing import Literal
from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import StorylineMemoryService
from chat_buddy.characters.domain import (
    ChangeMemoryStateCommand,
    ContinuityLifecycle,
    CorrectMemoryCommand,
    DeleteMemoryCommand,
    DismissMemoryConflictCommand,
    ExtractionEffectConflictError,
    GenerationConfiguration,
    MemoryConflict,
    MemoryConflictNotFoundError,
    MemoryConflictState,
    MemoryNotFoundError,
    MemoryRevisionState,
    MemorySubjectConflictError,
    ProtectedMemoryCorrectionError,
    StaleMemoryConflictError,
    StaleMemoryRevisionError,
    Storyline,
    StorylineMemory,
)

_CORRECTION_TARGET_KEY = "characters_storyline_memory_correction_target"


def render_storyline_memory(
    service: StorylineMemoryService,
    storyline: Storyline,
    selected_leaf_id: UUID | None,
) -> None:
    """Render one Storyline's memory lineages and extraction conflicts.

    Args:
        service:
            Provider-free memory management operations.
        storyline:
            Selected continuity and complete profile ownership.
        selected_leaf_id:
            Selected branch checkpoint used only to invalidate stale widgets.
    """

    memories = service.list_memories(storyline.id)
    conflicts = service.list_conflicts(storyline.id)
    read_only = storyline.lifecycle == ContinuityLifecycle.ARCHIVED

    st.divider()
    st.subheader("Storyline memory")
    st.caption(
        "Memory is scoped to this Storyline. It is never shared with Ongoing or Chat."
    )
    if read_only:
        st.info("Archived Storyline memory is read-only.")

    if not memories:
        st.info("No memories have been extracted for this Storyline yet.")
    for memory in memories:
        _render_memory(service, storyline, selected_leaf_id, memory, read_only)

    unresolved = tuple(
        conflict
        for conflict in conflicts
        if conflict.state == MemoryConflictState.UNRESOLVED
    )
    dismissed = tuple(
        conflict
        for conflict in conflicts
        if conflict.state == MemoryConflictState.DISMISSED
    )
    st.subheader("Memory conflicts")
    if not unresolved:
        st.info("No unresolved memory conflicts.")
    for conflict in unresolved:
        _render_conflict(
            service,
            storyline,
            selected_leaf_id,
            memories,
            conflict,
            read_only,
        )
    if dismissed:
        with st.expander(f"Dismissed conflicts ({len(dismissed)})"):
            for conflict in dismissed:
                st.markdown(f"**{conflict.proposed_subject}** — dismissed")
                st.write(conflict.proposed_content)


def clear_storyline_memory_state() -> None:
    """Discard continuity-owned memory form state after scope changes."""

    st.session_state.pop(_CORRECTION_TARGET_KEY, None)


def _render_memory(
    service: StorylineMemoryService,
    storyline: Storyline,
    selected_leaf_id: UUID | None,
    memory: StorylineMemory,
    read_only: bool,
) -> None:
    """Render one complete memory lineage and guarded lifecycle actions.

    Args:
        service:
            Memory management operations.
        storyline:
            Complete selected continuity ownership.
        selected_leaf_id:
            Selected branch checkpoint used to scope widgets.
        memory:
            Complete immutable memory lineage.
        read_only:
            Whether archival prevents mutations.
    """

    current = memory.current
    correction_target = _correction_target(storyline, selected_leaf_id, memory)
    label = f"{current.subject} · {current.state.value} · revision {current.revision}"
    with st.expander(label, expanded=correction_target):
        st.write(current.content)
        st.caption(
            f"Current state: {current.state.value}; authorship: "
            f"{current.authorship.value}; change: {current.kind.value}."
        )
        if len(memory.evidence) > 1:
            st.caption(
                f"Reinforced by {len(memory.evidence) - 1} additional source "
                f"turn{'s' if len(memory.evidence) != 2 else ''}."
            )
        _render_lineage(memory)
        _render_evidence(memory)
        if read_only:
            return
        if current.state == MemoryRevisionState.ACTIVE:
            _render_correction(service, storyline, selected_leaf_id, memory)
            if st.button(
                "Exclude memory",
                key=f"{_memory_key(storyline, selected_leaf_id, memory)}_exclude",
            ):
                _change_state(service, memory, "exclude")
        else:
            if st.button(
                "Reactivate memory",
                key=f"{_memory_key(storyline, selected_leaf_id, memory)}_reactivate",
            ):
                _change_state(service, memory, "reactivate")
        _render_deletion(service, storyline, selected_leaf_id, memory)


def _render_lineage(memory: StorylineMemory) -> None:
    """Render lifecycle and authorship provenance for every revision.

    Args:
        memory:
            Complete logical memory lineage.
    """

    with st.expander("Revision history"):
        for revision in reversed(memory.revisions):
            st.markdown(
                f"**Revision {revision.revision} · {revision.kind.value} · "
                f"{revision.authorship.value} · {revision.state.value}**"
            )
            st.write(f"{revision.subject}: {revision.content}")
            st.caption(f"Created {revision.created_at.isoformat()}")


def _render_evidence(memory: StorylineMemory) -> None:
    """Render source, temporal, and extraction-strategy provenance.

    Args:
        memory:
            Complete logical memory with supporting evidence.
    """

    with st.expander(f"Source evidence ({len(memory.evidence)})"):
        for index, evidence in enumerate(memory.evidence, start=1):
            extraction = evidence.extraction
            st.markdown(f"**Evidence {index} · scene {evidence.learned.position}**")
            st.write(
                f"Occurred in scene {evidence.occurrence.position}; learned in scene "
                f"{evidence.learned.position}; persona checkpoint "
                f"{evidence.persona_checkpoint}."
            )
            st.caption(
                f"Selector {extraction.selector.name} {extraction.selector.version}; "
                f"extractor {extraction.extractor.name} "
                f"{extraction.extractor.version}; prompt schema "
                f"{extraction.prompt_schema_version}; provider/model "
                f"{extraction.provider}/{extraction.model}; "
                f"configuration {_configuration_label(extraction.configuration)}; "
                f"created {evidence.created_at.isoformat()}."
            )


def _render_correction(
    service: StorylineMemoryService,
    storyline: Storyline,
    selected_leaf_id: UUID | None,
    memory: StorylineMemory,
) -> None:
    """Render a revision-guarded normal correction form.

    Args:
        service:
            Memory management operations.
        storyline:
            Complete selected continuity ownership.
        selected_leaf_id:
            Selected branch checkpoint used to scope the form.
        memory:
            Active memory snapshot to correct.
    """

    current = memory.current
    with st.form(f"{_memory_key(storyline, selected_leaf_id, memory)}_correction"):
        subject = st.text_input(
            "Corrected subject", value=current.subject, max_chars=256
        )
        content = st.text_area(
            "Corrected memory", value=current.content, max_chars=4096
        )
        submitted = st.form_submit_button("Save correction")
    if submitted:
        try:
            service.correct(
                CorrectMemoryCommand(
                    continuity_id=memory.continuity_id,
                    memory_id=memory.id,
                    expected_revision_id=current.id,
                    subject=subject,
                    content=content,
                )
            )
        except _MEMORY_ERRORS as error:
            st.warning(f"The memory changed or could not be corrected: {error}")
        else:
            clear_storyline_memory_state()
            st.rerun()


def _change_state(
    service: StorylineMemoryService,
    memory: StorylineMemory,
    operation: Literal["exclude", "reactivate"],
) -> None:
    """Apply one guarded exclusion or reactivation.

    Args:
        service:
            Memory management operations.
        memory:
            Last observed memory snapshot.
        operation:
            Requested lifecycle operation.
    """

    command = ChangeMemoryStateCommand(
        operation=operation,
        continuity_id=memory.continuity_id,
        memory_id=memory.id,
        expected_revision_id=memory.current.id,
    )
    try:
        if operation == "exclude":
            service.exclude(command)
        else:
            service.reactivate(command)
    except _MEMORY_ERRORS as error:
        st.warning(f"The memory changed or could not be updated: {error}")
    else:
        st.rerun()


def _render_deletion(
    service: StorylineMemoryService,
    storyline: Storyline,
    selected_leaf_id: UUID | None,
    memory: StorylineMemory,
) -> None:
    """Require explicit confirmation before permanently deleting a lineage.

    Args:
        service:
            Memory management operations.
        storyline:
            Complete selected continuity ownership.
        selected_leaf_id:
            Selected branch checkpoint used to scope confirmation.
        memory:
            Last observed memory snapshot.
    """

    key = _memory_key(storyline, selected_leaf_id, memory)
    confirmed = st.checkbox(
        "I understand this permanently deletes the complete memory and provenance.",
        key=f"{key}_delete_confirm",
    )
    if st.button(
        "Permanently delete memory",
        key=f"{key}_delete",
        disabled=not confirmed,
    ):
        try:
            service.delete(
                DeleteMemoryCommand(
                    continuity_id=memory.continuity_id,
                    memory_id=memory.id,
                    expected_revision_id=memory.current.id,
                )
            )
        except _MEMORY_ERRORS as error:
            st.warning(f"The memory changed or could not be deleted: {error}")
        else:
            clear_storyline_memory_state()
            st.rerun()


def _render_conflict(
    service: StorylineMemoryService,
    storyline: Storyline,
    selected_leaf_id: UUID | None,
    memories: tuple[StorylineMemory, ...],
    conflict: MemoryConflict,
    read_only: bool,
) -> None:
    """Render proposed evidence separately from current memory.

    Args:
        service:
            Memory management operations.
        storyline:
            Complete selected continuity ownership.
        selected_leaf_id:
            Selected branch checkpoint used to scope actions.
        memories:
            Continuity-owned memories available for target inspection.
        conflict:
            Unresolved extraction conflict.
        read_only:
            Whether archival prevents dismissal or correction.
    """

    target = next((row for row in memories if row.id == conflict.memory_id), None)
    key = (
        f"characters_memory_conflict_{storyline.identity_id}_{storyline.persona_id}_"
        f"{storyline.id}_{storyline.revision}_{selected_leaf_id}_{conflict.id}_"
        f"{conflict.observed_revision_id}"
    )
    with st.expander(f"Conflict: {conflict.proposed_subject}"):
        st.markdown("**New evidence proposes**")
        st.write(conflict.proposed_content)
        _render_conflict_evidence(conflict)
        st.markdown("**Current memory**")
        if target is None:
            st.write("This conflict does not target an existing memory.")
        else:
            st.write(f"{target.current.subject}: {target.current.content}")
            st.caption(
                f"Observed revision {conflict.observed_revision_id}; current revision "
                f"{target.current.id}."
            )
        if read_only:
            return
        if target is not None:
            if st.button("Correct current memory", key=f"{key}_correct"):
                st.session_state[_CORRECTION_TARGET_KEY] = (
                    storyline.identity_id,
                    storyline.persona_id,
                    storyline.id,
                    storyline.revision,
                    selected_leaf_id,
                    target.id,
                    target.current.id,
                )
                st.rerun()
            action_label = "Keep current value"
        else:
            action_label = "Dismiss conflict"
        if st.button(action_label, key=f"{key}_dismiss"):
            try:
                service.dismiss_conflict(
                    DismissMemoryConflictCommand(
                        continuity_id=storyline.id,
                        conflict_id=conflict.id,
                        expected_revision_id=conflict.observed_revision_id,
                    )
                )
            except _CONFLICT_ERRORS as error:
                st.warning(f"The conflict changed or could not be dismissed: {error}")
            else:
                st.rerun()


def _render_conflict_evidence(conflict: MemoryConflict) -> None:
    """Render the exact new source and temporal provenance for a conflict.

    Args:
        conflict:
            Conflict whose proposed evidence is being inspected.
    """

    evidence = conflict.evidence
    st.caption(
        f"New evidence: scene {evidence.learned.position}, occurrence scene "
        f"{evidence.occurrence.position}, persona checkpoint "
        f"{evidence.persona_checkpoint}, {evidence.extraction.provider}/"
        f"{evidence.extraction.model}, created {evidence.created_at.isoformat()}."
    )


def _correction_target(
    storyline: Storyline,
    selected_leaf_id: UUID | None,
    memory: StorylineMemory,
) -> bool:
    """Return whether a conflict action opened this exact correction snapshot.

    Args:
        storyline:
            Current selected Storyline snapshot.
        selected_leaf_id:
            Current selected branch checkpoint.
        memory:
            Current memory snapshot.

    Returns:
        Whether stored complete ownership and revisions still match.
    """

    return st.session_state.get(_CORRECTION_TARGET_KEY) == (
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        storyline.revision,
        selected_leaf_id,
        memory.id,
        memory.current.id,
    )


def _memory_key(
    storyline: Storyline,
    selected_leaf_id: UUID | None,
    memory: StorylineMemory,
) -> str:
    """Build a complete ownership- and revision-scoped widget namespace.

    Args:
        storyline:
            Current selected Storyline snapshot.
        selected_leaf_id:
            Current selected branch checkpoint.
        memory:
            Current memory snapshot.

    Returns:
        Stable unique prefix invalidated by continuity or revision changes.
    """

    return (
        f"characters_memory_{storyline.identity_id}_{storyline.persona_id}_"
        f"{storyline.id}_{storyline.revision}_{selected_leaf_id}_{memory.id}_"
        f"{memory.current.id}"
    )


def _configuration_label(configuration: GenerationConfiguration) -> str:
    """Render effective non-secret extraction settings compactly.

    Args:
        configuration:
            Pydantic generation configuration snapshot.

    Returns:
        Stable setting list, including explicit provider defaults when absent.
    """

    values = configuration.model_dump()
    return ", ".join(
        f"{name}={value if value is not None else 'provider default'}"
        for name, value in values.items()
    )


_MEMORY_ERRORS = (
    MemoryNotFoundError,
    StaleMemoryRevisionError,
    ProtectedMemoryCorrectionError,
    MemorySubjectConflictError,
)
_CONFLICT_ERRORS = (
    MemoryConflictNotFoundError,
    StaleMemoryConflictError,
    ExtractionEffectConflictError,
)
