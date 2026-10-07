"""Scoped durable Ongoing history, streaming, and recovery controls."""

from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ContextCapacityError,
    Continuity,
    ContinuityLifecycle,
    ConversationGraphView,
    ConversationHistory,
    ConversationScope,
    ConversationSettings,
    GenerationAttempt,
    GenerationConfiguration,
    GraphNodeView,
    ProviderInvocationError,
    StaleSelectionError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure import create_conversation_service


def render_ongoing(continuity: Continuity) -> None:
    """Restore and converse within the selected continuity only.

    Args:
        continuity:
            Ownership-checked selected continuity and lifecycle.
    """

    service = create_conversation_service()
    scope = ConversationScope(
        identity_id=continuity.identity_id,
        persona_id=continuity.persona_id,
        continuity_id=continuity.id,
        conversation_id=continuity.conversation_id,
    )
    key = f"characters_ongoing_{continuity.id}_{continuity.conversation_id}"
    try:
        history = service.resume(scope)
        graph = service.inspect_graph(scope)
        archived = continuity.lifecycle == ContinuityLifecycle.ARCHIVED
        active = any(
            attempt.status in {"pending", "streaming"} for attempt in history.attempts
        )

        unmatched = bool(history.messages and history.messages[-1].role == "user")
        _transcript(service, history, graph, key, archived or active)
        if unmatched:
            for attempt in history.attempts:
                if attempt.user_message_id != history.messages[-1].id:
                    continue
                with st.expander(
                    f"Incomplete attempt · {attempt.status}", expanded=True
                ):
                    st.caption(
                        f"{attempt.generation.model.provider} / {attempt.generation.model.model}"
                    )
                    st.markdown(attempt.incomplete_output or "No output saved.")
        _configuration(service, scope, history.settings, key, archived or active)

        if active:
            st.info(
                "An attempt is active. Refresh to reload progress. Abandoned attempts become recoverable after five minutes without progress."
            )
            if st.button("Refresh progress", key=f"{key}_refresh"):
                st.rerun()
        continuation = unmatched and st.button(
            "Continue incomplete turn",
            disabled=archived or active,
            key=f"{key}_continue",
        )
        submitted = st.chat_input(
            "Message persona",
            disabled=archived or active or unmatched,
            key=f"{key}_input",
        )
        if continuation or submitted:
            attempt = (
                service.continue_incomplete_turn(scope)
                if continuation
                else service.send(scope, SubmittedInput(content=submitted or ""))
            )
            if submitted:
                with st.chat_message("user"):
                    st.markdown(submitted)
            _stream_attempt(service, scope, attempt)
            st.rerun()
    except StaleSelectionError:
        st.warning("The selected future changed. Reloading its latest saved state.")
        st.rerun()
    except ContextCapacityError as error:
        st.error(str(error))
        st.info(
            "Choose a model with a larger context window or reduce the output limit. If summary compression failed, check the summary model and try again. Shorten a new message before resubmitting."
        )
    except ProviderInvocationError as error:
        st.error(str(error))
        st.info(
            "Check the provider connection and model availability, then reload and continue the incomplete turn. Saved partial output is separate from completed history."
        )
        if st.button("Reload saved turn", key=f"{key}_reload"):
            st.rerun()
    except (ValueError, LookupError) as error:
        st.error(str(error))
        st.info("Reload the continuity to inspect its saved state before continuing.")


def _transcript(
    service: ConversationService,
    history: ConversationHistory,
    graph: ConversationGraphView,
    key: str,
    writes_disabled: bool,
) -> None:
    """Render the selected path and every valid graph action.

    Args:
        service:
            Conversation application service.
        history:
            Selected committed transcript and attempt state.
        graph:
            Detached complete graph action view.
        key:
            Full-scope widget namespace.
        writes_disabled:
            Whether archival or an open attempt blocks graph writes.
    """

    views = {node.message.id: node for node in graph.nodes}
    displayed_alternatives: set[UUID] = set()
    for message in history.messages:
        view = views.get(message.id)
        with st.chat_message("user" if message.role == "user" else "assistant"):
            st.markdown(message.content)
            if view is None or message.role != "persona":
                continue
            _response_details(view)
            displayed_alternatives.update(
                _alternatives(service, graph, view, views, key, writes_disabled)
            )
            _response_actions(service, graph, view, key, writes_disabled)
    _saved_futures(
        service,
        graph,
        displayed_alternatives,
        key,
        writes_disabled,
    )


def _response_details(view: GraphNodeView, compact: bool = False) -> None:
    """Show retry accounting and immutable response provenance.

    Args:
        view:
            Persona graph node and derived action metadata.
        compact:
            Whether the response is already inside another expander.
    """

    provenance = view.message.response_provenance
    if provenance is None:
        return
    generation = provenance.generation
    configuration = ", ".join(
        f"{name}={value}"
        for name, value in generation.configuration.model_dump(
            exclude_none=True
        ).items()
    )
    st.caption(
        f"{generation.model.provider} / {generation.model.model} · "
        f"{view.retry_count} of 3 retries used"
    )
    generation_detail = (
        f"Generation: {configuration} · input budget: "
        f"{generation.input_tokens} tokens"
    )
    behavior_detail = (
        f"Style: {provenance.response_style.name} "
        f"{provenance.response_style.version} · evolution: "
        f"{provenance.evolution_strategy.name} "
        f"{provenance.evolution_strategy.version}"
    )
    if compact:
        st.caption(generation_detail)
        st.caption(behavior_detail)
        st.caption(f"Attempt: {provenance.attempt_id}")
        return
    with st.expander("Response provenance"):
        st.caption(generation_detail)
        st.caption(behavior_detail)
        st.caption(f"Attempt: {provenance.attempt_id}")


def _alternatives(
    service: ConversationService,
    graph: ConversationGraphView,
    selected: GraphNodeView,
    views: dict[UUID, GraphNodeView],
    key: str,
    writes_disabled: bool,
) -> set[UUID]:
    """Render persona siblings for one selected user turn.

    Args:
        service:
            Conversation application service.
        graph:
            Complete graph view carrying the compare-and-swap guard.
        selected:
            Selected persona response for this turn.
        views:
            Graph views indexed by message identifier.
        key:
            Full-scope widget namespace.
        writes_disabled:
            Whether graph writes are currently blocked.

    Returns:
        Alternative identifiers rendered for duplicate suppression.
    """

    alternative_ids = set(selected.alternative_ids) - {selected.message.id}
    if not alternative_ids:
        return set()
    with st.expander(f"Alternatives · {len(selected.alternative_ids)} responses saved"):
        for alternative_id in selected.alternative_ids:
            if alternative_id == selected.message.id:
                continue
            alternative = views[alternative_id]
            st.markdown(alternative.message.content)
            _response_details(alternative, compact=True)
            if st.button(
                "Select alternative",
                disabled=writes_disabled,
                key=f"{key}_select_{alternative_id}",
            ):
                _select(service, graph, alternative.message.id)
    return alternative_ids


def _response_actions(
    service: ConversationService,
    graph: ConversationGraphView,
    view: GraphNodeView,
    key: str,
    writes_disabled: bool,
) -> None:
    """Render valid retry and confirmed branch controls for one response.

    Args:
        service:
            Conversation application service.
        graph:
            Complete graph view carrying the compare-and-swap guard.
        view:
            Selected persona response action metadata.
        key:
            Full-scope widget namespace.
        writes_disabled:
            Whether graph writes are currently blocked.
    """

    if (
        view.selected_leaf
        and view.retry_count < 3
        and not writes_disabled
        and st.button("Retry response", key=f"{key}_retry_{view.message.id}")
    ):
        attempt = service.retry_completed_response(graph.scope)
        _stream_attempt(service, graph.scope, attempt)
        st.rerun()
    if not view.branchable or writes_disabled:
        return
    confirmed = st.checkbox(
        "I understand this keeps the current future saved.",
        key=f"{key}_branch_confirm_{view.message.id}",
    )
    if st.button(
        "Branch from here",
        disabled=not confirmed,
        key=f"{key}_branch_{view.message.id}",
    ):
        selected_leaf_id = _selected_leaf(graph)
        service.branch_from_here(
            graph.scope,
            view.message.id,
            selected_leaf_id,
        )
        st.rerun()


def _saved_futures(
    service: ConversationService,
    graph: ConversationGraphView,
    displayed_alternatives: set[UUID],
    key: str,
    writes_disabled: bool,
) -> None:
    """Render exact off-path leaves so abandoned futures remain revisitable.

    Args:
        service:
            Conversation application service.
        graph:
            Complete graph view carrying the compare-and-swap guard.
        displayed_alternatives:
            Off-path responses already displayed beside a selected turn.
        key:
            Full-scope widget namespace.
        writes_disabled:
            Whether graph writes are currently blocked.
    """

    parent_ids = {
        node.message.parent_id
        for node in graph.nodes
        if node.message.parent_id is not None
    }
    futures = tuple(
        node
        for node in graph.nodes
        if node.message.role == "persona"
        and not node.selected
        and node.message.id not in parent_ids
        and node.message.id not in displayed_alternatives
    )
    if not futures:
        return
    with st.expander(f"Saved futures · {len(futures)}"):
        for future in futures:
            st.markdown(future.message.content)
            _response_details(future, compact=True)
            if st.button(
                "Select alternative",
                disabled=writes_disabled,
                key=f"{key}_future_{future.message.id}",
            ):
                _select(service, graph, future.message.id)


def _select(
    service: ConversationService,
    graph: ConversationGraphView,
    message_id: UUID,
) -> None:
    """Select one exact saved persona response and reload.

    Args:
        service:
            Conversation application service.
        graph:
            Complete graph view carrying the compare-and-swap guard.
        message_id:
            Exact persona node to select.
    """

    service.select_saved_future(
        graph.scope,
        message_id,
        _selected_leaf(graph),
    )
    st.rerun()


def _selected_leaf(graph: ConversationGraphView) -> UUID:
    """Return the nonempty selected leaf required by graph controls.

    Args:
        graph:
            Complete graph action view.

    Returns:
        Exact selected leaf identifier.

    Raises:
        ValueError:
            If a graph control is rendered without a selected leaf.
    """

    if graph.selected_leaf_id is None:
        raise ValueError("A graph action requires a selected response")
    return graph.selected_leaf_id


def _stream_attempt(
    service: ConversationService,
    scope: ConversationScope,
    attempt: GenerationAttempt,
) -> None:
    """Render and exhaust one durable generation attempt.

    Args:
        service:
            Conversation application service.
        scope:
            Complete conversation ownership.
        attempt:
            Reserved attempt to stream.
    """

    with st.chat_message("assistant"):
        st.caption("Generating · output is incomplete until the response is saved.")
        output = st.empty()
        chunks = ""
        stream = service.stream(scope, attempt.id)
        try:
            for chunk in stream:
                chunks += chunk
                output.markdown(chunks)
        finally:
            stream.close()


def _configuration(
    service: ConversationService,
    scope: ConversationScope,
    saved: ConversationSettings | None,
    key: str,
    disabled: bool,
) -> None:
    """Persist supported configuration for future attempts through the service.

    Args:
        service:
            Conversation application service.
        scope:
            Complete ownership.
        saved:
            Durable selection, absent before first use.
        key:
            Continuity-specific widget namespace.
        disabled:
            Whether the scope currently disallows changes.
    """

    settings = saved or service.default_settings()
    models = service.response_models()
    options = [(model.provider, model.model) for model in models]
    selected_key = (settings.provider, settings.model)
    if selected_key not in options:
        options.append(selected_key)
        st.warning("Saved model is unavailable. Select a configured response model.")
    with st.expander("Response model and generation"):
        selected = st.selectbox(
            "Response model",
            options,
            index=options.index(selected_key),
            format_func=lambda value: f"{value[0]} / {value[1]}",
            disabled=disabled,
            key=f"{key}_model",
        )
        descriptor = next(
            (model for model in models if (model.provider, model.model) == selected),
            None,
        )
        if descriptor is None:
            return
        requested = settings.requested

        # Model-specific keys prevent unsupported overrides following a model switch.
        parameter_key = f"{key}_{selected[0]}_{selected[1]}"
        values: dict[str, object] = {}
        for name in ("max_output_tokens", "temperature", "top_p", "seed"):
            if name != "max_output_tokens" and name not in descriptor.parameters:
                continue
            value = getattr(requested, name) if selected == selected_key else None
            values[name] = (
                st.text_input(
                    name.replace("_", " ").capitalize() + " (blank uses model default)",
                    value=str(value) if value is not None else "",
                    disabled=disabled,
                    key=f"{parameter_key}_{name}",
                )
                or None
            )
        st.caption(
            "Saved changes apply to the next attempt. Prior responses keep their original settings."
        )
        if st.button(
            "Save generation settings", disabled=disabled, key=f"{key}_configure"
        ):
            service.configure(
                scope,
                ConversationSettings(
                    provider=selected[0],
                    model=selected[1],
                    requested=GenerationConfiguration.model_validate(values),
                ),
            )
            st.success("Settings saved for the next attempt.")
