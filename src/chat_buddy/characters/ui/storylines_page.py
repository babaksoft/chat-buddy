"""Focused Storyline navigation and scene-management page."""

from uuid import UUID, uuid4

import streamlit as st

from chat_buddy.characters.application import (
    ConversationService,
    IdentityService,
    PersonaService,
    StorylineForkService,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ContinuityLifecycle,
    ContinuityMode,
    ConversationGraphView,
    ConversationTarget,
    EvolutionScope,
    GraphNodeView,
    Identity,
    IncompleteLatestSceneError,
    LockedSceneSetupError,
    Persona,
    ResponseStyleSnapshot,
    Scene,
    SceneAppendEligibility,
    SceneDetails,
    SceneSequence,
    StaleSelectionError,
    StaleStorylineError,
    Storyline,
    StorylineForkConflictError,
    StorylineForkPreview,
    StorylineGroup,
)
from chat_buddy.characters.infrastructure import (
    create_conversation_service,
    create_evolution_inspection_service,
    create_storyline_fork_service,
    create_storyline_memory_service,
    create_storyline_services,
)
from chat_buddy.characters.ui.evolution_inspection import (
    render_evolution_inspection,
)
from chat_buddy.characters.ui.new_storyline_page import render_new_storyline
from chat_buddy.characters.ui.ongoing import render_conversation
from chat_buddy.characters.ui.storyline_memory import (
    clear_storyline_memory_state,
    render_storyline_memory,
)

_SCOPE_KEY = "characters_storyline_scope"
_STYLE = ResponseStyleSnapshot(
    name="storyline.default",
    version="1.0.0",
    instruction="Respond naturally within the current scene.",
)


def render_storylines_page() -> None:
    """Render ownership-scoped Storyline navigation and scene management."""

    st.title("📚 Storylines")
    identities, personas, storylines = create_storyline_services()
    try:
        identities.ensure_default()
        _render_page(identities, personas, storylines)
    except (ValueError, LookupError) as error:
        st.error(str(error))


def _render_page(
    identities: IdentityService,
    personas: PersonaService,
    storylines: StorylineService,
) -> None:
    """Render navigation and the selected Storyline.

    Args:
        identities:
            Identity application operations.
        personas:
            Persona application operations.
        storylines:
            Storyline lifecycle operations.
    """

    identity_rows = identities.list()
    persona_rows = personas.list()
    groups = storylines.list_grouped()
    with st.sidebar:
        _render_hierarchy(identity_rows, persona_rows, groups, storylines)

    sequence = _selected_sequence(groups, storylines)
    if sequence is None:
        if not persona_rows:
            st.info("Create a persona before starting a Storyline.")
        else:
            st.info(
                "Select a Storyline from the sidebar, or choose a pair to start one."
            )
        return

    identity = next(
        row for row in identity_rows if row.id == sequence.storyline.identity_id
    )
    persona = next(
        row for row in persona_rows if row.id == sequence.storyline.persona_id
    )
    _render_storyline(identity, persona, sequence, storylines)


def _render_hierarchy(
    identities: list[Identity],
    personas: list[Persona],
    groups: tuple[StorylineGroup, ...],
    service: StorylineService,
) -> None:
    """Render every pair with active and archived Storylines separated.

    Args:
        identities:
            Persisted identity snapshots.
        personas:
            Persisted persona snapshots.
        groups:
            Storylines grouped by complete ownership.
        service:
            Storyline lifecycle operations.
    """

    st.header("Identity → Persona → Storylines")
    grouped = {(row.identity_id, row.persona_id): row.storylines for row in groups}
    for identity in identities:
        with st.expander(identity.details.name, expanded=len(identities) == 1):
            if not personas:
                st.caption("No personas yet")
                continue
            for persona in personas:
                st.markdown(f"**{persona.core.name}**")
                rows = grouped.get((identity.id, persona.id), ())
                active = tuple(
                    row for row in rows if row.lifecycle == ContinuityLifecycle.ACTIVE
                )
                archived = tuple(
                    row for row in rows if row.lifecycle == ContinuityLifecycle.ARCHIVED
                )
                if active:
                    st.caption("Active")
                    _render_storyline_buttons(identity.id, persona.id, active)
                if archived:
                    st.caption("Archived")
                    _render_storyline_buttons(identity.id, persona.id, archived)
                availability = service.start_availability(identity.id, persona.id)
                if st.button(
                    "New Storyline",
                    key=f"characters_new_storyline_{identity.id}_{persona.id}",
                    disabled=not availability.can_start,
                    help=availability.reason,
                    use_container_width=True,
                ):
                    _prepare_start(identity.id, persona.id)
                if availability.reason is not None:
                    st.caption(availability.reason)


def _render_storyline_buttons(
    identity_id: UUID, persona_id: UUID, storylines: tuple[Storyline, ...]
) -> None:
    """Render selection buttons for one lifecycle group.

    Args:
        identity_id:
            Shared identity owner.
        persona_id:
            Shared persona owner.
        storylines:
            Storyline snapshots in the lifecycle group.
    """

    for storyline in storylines:
        if st.button(
            storyline.name,
            key=f"characters_select_storyline_{storyline.id}",
            use_container_width=True,
        ):
            _store_scope(identity_id, persona_id, storyline.id)
            st.rerun()


def _selected_sequence(
    groups: tuple[StorylineGroup, ...], service: StorylineService
) -> SceneSequence | None:
    """Validate stored ownership before loading a Storyline.

    Args:
        groups:
            Current ownership-grouped Storylines.
        service:
            Storyline lifecycle operations.

    Returns:
        Owned scene sequence or no selection.
    """

    scope = st.session_state.get(_SCOPE_KEY)
    if not (
        isinstance(scope, tuple)
        and len(scope) == 3
        and all(isinstance(identifier, UUID) for identifier in scope)
    ):
        return None
    identity_id, persona_id, storyline_id = scope
    valid = any(
        group.identity_id == identity_id
        and group.persona_id == persona_id
        and any(row.id == storyline_id for row in group.storylines)
        for group in groups
    )
    if not valid:
        _clear_selection()
        return None
    return service.resume(identity_id, persona_id, storyline_id)


def _render_storyline(
    identity: Identity,
    persona: Persona,
    sequence: SceneSequence,
    service: StorylineService,
) -> None:
    """Render selected Storyline metadata and guarded scene actions.

    Args:
        identity:
            Owning identity snapshot.
        persona:
            Owning persona snapshot.
        sequence:
            Current Storyline and ordered scenes.
        service:
            Storyline lifecycle operations.
    """

    storyline = sequence.storyline
    st.subheader(storyline.name)
    st.caption(
        f"{identity.details.name} and {persona.core.name} · "
        f"{storyline.lifecycle.value.capitalize()}"
    )
    if storyline.lifecycle == ContinuityLifecycle.ARCHIVED:
        st.info("Archived Storylines are read-only.")
    else:
        _render_storyline_actions(sequence, service)

    st.write("Scenes")
    selected = _selected_scene(sequence)
    for scene in sequence.scenes:
        if st.button(
            f"{scene.position}. {scene.details.title}",
            key=f"characters_select_scene_{scene.id}",
            type="primary" if scene.id == selected.id else "secondary",
        ):
            st.session_state["characters_scene_id"] = scene.id
            st.rerun()
    selected_leaf_id = _render_scene(selected, sequence, service)
    render_storyline_memory(
        create_storyline_memory_service(), storyline, selected_leaf_id
    )
    render_evolution_inspection(
        create_evolution_inspection_service(),
        EvolutionScope(
            identity_id=storyline.identity_id,
            persona_id=storyline.persona_id,
            continuity_id=storyline.id,
        ),
        storyline.relationship,
        storyline.lifecycle,
    )


def _render_storyline_actions(
    sequence: SceneSequence, service: StorylineService
) -> None:
    """Render rename, archive, resume-latest, and append choices.

    Args:
        sequence:
            Current Storyline and ordered scenes.
        service:
            Storyline lifecycle operations.
    """

    storyline = sequence.storyline
    latest = sequence.scenes[-1]
    key = f"characters_storyline_name_{storyline.id}_{storyline.revision}"
    with st.form(key):
        name = st.text_input("Storyline name", value=storyline.name, max_chars=128)
        rename = st.form_submit_button("Rename Storyline")
    if rename:
        try:
            service.rename(
                storyline.identity_id,
                storyline.persona_id,
                storyline.id,
                name,
                storyline.revision,
            )
        except StaleStorylineError:
            st.warning(
                "The Storyline changed. Review the latest version and try again."
            )
        else:
            st.rerun()

    if st.button("Resume latest scene", key=f"characters_resume_latest_{storyline.id}"):
        st.session_state["characters_scene_id"] = latest.id
        st.rerun()

    eligibility = service.append_eligibility(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    _render_next_scene(sequence, eligibility, service)

    if st.button("Archive Storyline", key=f"characters_archive_{storyline.id}"):
        try:
            service.archive(
                storyline.identity_id,
                storyline.persona_id,
                storyline.id,
                storyline.revision,
            )
        except StaleStorylineError:
            st.warning(
                "The Storyline changed. Review the latest version and try again."
            )
        else:
            st.rerun()


def _render_next_scene(
    sequence: SceneSequence,
    eligibility: SceneAppendEligibility,
    service: StorylineService,
) -> None:
    """Render a guarded next-scene form from observed eligibility.

    Args:
        sequence:
            Current Storyline and ordered scenes.
        eligibility:
            Application-derived append guards.
        service:
            Storyline lifecycle operations.
    """

    reason = _append_reason(eligibility)
    with st.form(
        f"characters_next_scene_{sequence.storyline.id}_{sequence.storyline.revision}"
    ):
        title = st.text_input("Next scene title", max_chars=128)
        setup = st.text_area("Next scene setup", max_chars=8192)
        append = st.form_submit_button(
            "Next scene", disabled=not eligibility.can_append, help=reason
        )
    if reason is not None:
        st.caption(reason)
    if append:
        try:
            updated = service.append_next(
                SceneDetails(title=title, setup=setup, response_style=_STYLE),
                eligibility,
            )
        except (IncompleteLatestSceneError, StaleSelectionError, StaleStorylineError):
            st.warning(
                "The latest scene changed or is no longer complete. Review it before appending."
            )
        else:
            st.session_state["characters_scene_id"] = updated.scenes[-1].id
            st.rerun()


def _render_scene(
    scene: Scene, sequence: SceneSequence, service: StorylineService
) -> UUID | None:
    """Render one selected scene and its writable presentation fields.

    Args:
        scene:
            Selected owned scene.
        sequence:
            Current Storyline and ordered scenes.
        service:
            Storyline lifecycle operations.

    Returns:
        Selected branch leaf for memory-widget invalidation, when present.
    """

    storyline = sequence.storyline
    st.subheader(f"Scene {scene.position}: {scene.details.title}")
    st.write(scene.details.setup)
    st.caption(
        f"Style: {scene.details.response_style.name} "
        f"{scene.details.response_style.version}"
    )
    if storyline.lifecycle == ContinuityLifecycle.ARCHIVED:
        return _render_scene_conversation(scene, sequence)

    key = f"characters_scene_title_{scene.id}_{storyline.revision}"
    with st.form(key):
        title = st.text_input("Scene title", value=scene.details.title, max_chars=128)
        rename = st.form_submit_button("Rename scene")
    if rename:
        try:
            service.rename_scene(scene.scope, scene.id, title, storyline.revision)
        except (ArchivedContinuityError, StaleStorylineError):
            st.warning("The Storyline changed. Review the scene and try again.")
        else:
            st.rerun()

    is_latest = scene.id == sequence.scenes[-1].id
    if is_latest and not scene.setup_locked:
        setup_key = f"characters_scene_setup_{scene.id}_{storyline.revision}"
        with st.form(setup_key):
            setup = st.text_area(
                "Scene setup", value=scene.details.setup, max_chars=8192
            )
            replace = st.form_submit_button("Save setup")
        if replace:
            try:
                service.replace_scene_setup(
                    scene.scope, scene.id, setup, storyline.revision
                )
            except (
                ArchivedContinuityError,
                LockedSceneSetupError,
                StaleStorylineError,
            ):
                st.warning(
                    "The scene setup is locked or changed. Review the latest scene."
                )
            else:
                st.rerun()
    else:
        st.caption("Scene setup is locked after its first user message.")

    return _render_scene_conversation(scene, sequence)


def _render_scene_conversation(scene: Scene, sequence: SceneSequence) -> UUID | None:
    """Render one scene conversation with Storyline-specific branch policy.

    Args:
        scene:
            Selected owned scene.
        sequence:
            Current Storyline and ordered scenes.

    Returns:
        Selected persona leaf identifier, when the scene graph is nonempty.
    """

    st.divider()
    target = ConversationTarget(
        scope=scene.scope,
        mode=ContinuityMode.STORYLINE,
        scene_id=scene.id,
    )
    conversation = create_conversation_service()
    forks = create_storyline_fork_service()
    identities, personas, _ = create_storyline_services()
    return render_conversation(
        conversation,
        target,
        f"characters_storyline_scene_{scene.id}",
        sequence.storyline.lifecycle == ContinuityLifecycle.ARCHIVED,
        lambda service, owned_target, graph, view, key, disabled: (
            _render_storyline_branch(
                service,
                forks,
                identities,
                personas,
                sequence,
                owned_target,
                graph,
                view,
                key,
                disabled,
            )
        ),
        read_only=scene.id != sequence.scenes[-1].id,
    )


def _render_storyline_branch(
    conversation: ConversationService,
    forks: StorylineForkService,
    identities: IdentityService,
    personas: PersonaService,
    sequence: SceneSequence,
    target: ConversationTarget,
    graph: ConversationGraphView,
    view: GraphNodeView,
    key: str,
    disabled: bool,
) -> None:
    """Render in-place branching or a reviewed structural fork.

    Args:
        conversation:
            Conversation graph application operations.
        forks:
            Reviewed structural fork operations.
        identities:
            Identity duplication operations.
        personas:
            Persona duplication operations.
        sequence:
            Current Storyline revision and scene chronology.
        target:
            Exact selected scene target.
        graph:
            Observed graph and selection guard.
        view:
            Persona message offered as a branch point.
        key:
            Full ownership-scoped widget namespace.
        disabled:
            Whether archival or an open attempt blocks branching.
    """

    if not view.branchable or disabled:
        return
    decision = conversation.branch_decision(target, view.message.id)
    if decision.disposition == "in_place":
        confirmed = st.checkbox(
            "I understand this keeps the current future saved.",
            key=f"{key}_branch_confirm_{view.message.id}",
        )
        if st.button(
            "Branch from here",
            disabled=not confirmed,
            key=f"{key}_branch_{view.message.id}",
        ):
            conversation.branch_from_here(
                target, view.message.id, _selected_leaf(graph)
            )
            st.rerun()
        return

    _render_fork_review(
        forks,
        identities,
        personas,
        sequence,
        target,
        graph,
        view,
        key,
    )


def _render_fork_review(
    forks: StorylineForkService,
    identities: IdentityService,
    personas: PersonaService,
    sequence: SceneSequence,
    target: ConversationTarget,
    graph: ConversationGraphView,
    view: GraphNodeView,
    key: str,
) -> None:
    """Prepare and confirm an explicitly named older-scene fork.

    Args:
        forks:
            Reviewed structural fork operations.
        identities:
            Identity duplication operations.
        personas:
            Persona duplication operations.
        sequence:
            Current Storyline revision and scene chronology.
        target:
            Exact older-scene target.
        graph:
            Observed graph and selected leaf.
        view:
            Exact persona branch point.
        key:
            Full ownership-scoped widget namespace.
    """

    preview_key = f"{key}_fork_preview_{view.message.id}"
    with st.expander("Fork Storyline from here"):
        st.info(
            "A fork keeps this Storyline unchanged and creates an independent "
            "Storyline under a distinct profile pair."
        )
        name = st.text_input(
            "Fork Storyline name",
            value=f"{sequence.storyline.name} fork",
            max_chars=128,
            key=f"{key}_fork_name_{view.message.id}",
        )
        duplicate = st.radio(
            "Profile to duplicate exactly",
            ("Identity", "Persona"),
            horizontal=True,
            key=f"{key}_fork_profile_{view.message.id}",
        )
        if st.button(
            "Review Storyline fork", key=f"{key}_fork_review_{view.message.id}"
        ):
            try:
                preview = _prepare_fork_preview(
                    forks,
                    identities,
                    personas,
                    sequence,
                    target,
                    graph,
                    view,
                    name,
                    duplicate,
                )
            except (StorylineForkConflictError, StaleStorylineError) as error:
                st.warning(str(error))
            else:
                st.session_state[preview_key] = preview
                st.rerun()

        stored_preview = st.session_state.get(preview_key)
        if not isinstance(stored_preview, StorylineForkPreview):
            return
        preview = stored_preview
        st.warning(
            f"Confirm ‘{preview.name}’ with duplicated "
            f"{preview.target_identity.details.name} / "
            f"{preview.target_persona.core.name}. The source selection will not change."
        )
        if st.button(
            "Confirm Storyline fork", key=f"{key}_fork_confirm_{view.message.id}"
        ):
            try:
                result = forks.confirm(preview)
            except (StorylineForkConflictError, StaleStorylineError) as error:
                st.session_state.pop(preview_key, None)
                st.warning(f"The fork preview is stale: {error}")
            else:
                _store_scope(
                    result.storyline.identity_id,
                    result.storyline.persona_id,
                    result.storyline.id,
                )
                st.session_state["characters_scene_id"] = result.scenes[-1].id
                st.session_state.pop(preview_key, None)
                st.rerun()


def _prepare_fork_preview(
    forks: StorylineForkService,
    identities: IdentityService,
    personas: PersonaService,
    sequence: SceneSequence,
    target: ConversationTarget,
    graph: ConversationGraphView,
    view: GraphNodeView,
    name: str,
    duplicate: str,
) -> StorylineForkPreview:
    """Create one exact profile duplicate and return a guarded preview.

    Args:
        forks:
            Reviewed structural fork operations.
        identities:
            Identity duplication operations.
        personas:
            Persona duplication operations.
        sequence:
            Current source Storyline snapshot.
        target:
            Exact older-scene target.
        graph:
            Observed graph and selected leaf.
        view:
            Exact persona branch point.
        name:
            Authored target Storyline name.
        duplicate:
            Profile kind selected for exact duplication.

    Returns:
        Immutable fork preview ready for explicit confirmation.
    """

    storyline = sequence.storyline
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 128:
        raise StorylineForkConflictError(
            "A fork Storyline name must contain 1 to 128 characters"
        )
    if duplicate == "Identity":
        target_identity_id = identities.duplicate(storyline.identity_id).id
        target_persona_id = storyline.persona_id
    else:
        target_identity_id = storyline.identity_id
        target_persona_id = personas.duplicate(storyline.persona_id).id
    return forks.preview(
        request_id=uuid4(),
        name=normalized_name,
        target=target,
        branch_point_message_id=view.message.id,
        expected_selected_leaf_id=_selected_leaf(graph),
        expected_storyline_revision=storyline.revision,
        target_identity_id=target_identity_id,
        target_persona_id=target_persona_id,
    )


def _selected_leaf(graph: ConversationGraphView) -> UUID:
    """Return the exact nonempty graph selection.

    Args:
        graph:
            Observed complete graph view.

    Returns:
        Exact selected persona leaf identifier.

    Raises:
        ValueError:
            If a branch is somehow offered for an empty graph.
    """

    if graph.selected_leaf_id is None:
        raise ValueError("A Storyline branch requires a selected response")
    return graph.selected_leaf_id


def _selected_scene(sequence: SceneSequence) -> Scene:
    """Resolve a selected owned scene, defaulting to the latest.

    Args:
        sequence:
            Current owned scene sequence.

    Returns:
        Selected scene or the latest scene.
    """

    selected_id = st.session_state.get("characters_scene_id")
    selected = next(
        (scene for scene in sequence.scenes if scene.id == selected_id),
        sequence.scenes[-1],
    )
    st.session_state["characters_scene_id"] = selected.id
    return selected


def _append_reason(eligibility: SceneAppendEligibility) -> str | None:
    """Translate an append block into concise user guidance.

    Args:
        eligibility:
            Application-derived append facts.

    Returns:
        Human-readable reason or None when append is allowed.
    """

    reasons = {
        "archived_storyline": "Archived Storylines cannot add scenes.",
        "not_latest_scene": "Only the latest scene can be followed.",
        "no_complete_exchange": "Complete one exchange before adding the next scene.",
        "unmatched_input": "Finish the pending response before adding a scene.",
        "open_attempt": "Wait for the open response attempt to finish.",
    }
    return (
        None if eligibility.block_reason is None else reasons[eligibility.block_reason]
    )


def _store_scope(identity_id: UUID, persona_id: UUID, storyline_id: UUID) -> None:
    """Store a complete selected Storyline scope atomically.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
        storyline_id:
            Selected Storyline.
    """

    st.session_state[_SCOPE_KEY] = (identity_id, persona_id, storyline_id)
    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    st.session_state["characters_storyline_id"] = storyline_id
    st.session_state.pop("characters_scene_id", None)
    clear_storyline_memory_state()


def _clear_selection() -> None:
    """Clear a stale Storyline and scene selection."""

    st.session_state.pop(_SCOPE_KEY, None)
    st.session_state.pop("characters_storyline_id", None)
    st.session_state.pop("characters_scene_id", None)
    clear_storyline_memory_state()


def _prepare_start(identity_id: UUID, persona_id: UUID) -> None:
    """Retain a pair and open the dedicated start workflow.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
    """

    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    st.session_state.pop("characters_new_storyline_identity", None)
    st.session_state.pop("characters_new_storyline_persona", None)
    _navigate_to_new_storyline()


def _navigate_to_new_storyline() -> None:
    """Navigate to the dedicated Storyline definition page."""

    st.switch_page(
        st.Page(
            render_new_storyline,
            title="New Storyline",
            icon="✨",
            url_path="new-storyline",
        )
    )
