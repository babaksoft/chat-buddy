"""Scoped durable Ongoing history, streaming, and recovery controls."""

import streamlit as st

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ContextCapacityError,
    Continuity,
    ContinuityLifecycle,
    ConversationScope,
    ConversationSettings,
    GenerationConfiguration,
    ProviderInvocationError,
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
    key = f"characters_ongoing_{continuity.id}"
    try:
        history = service.resume(scope)
        archived = continuity.lifecycle == ContinuityLifecycle.ARCHIVED
        active = any(
            attempt.status in {"pending", "streaming"} for attempt in history.attempts
        )

        unmatched = bool(history.messages and history.messages[-1].role == "user")
        for message in history.messages:
            with st.chat_message("user" if message.role == "user" else "assistant"):
                st.markdown(message.content)
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
            with st.chat_message("assistant"):
                st.caption(
                    "Generating · output is incomplete until the response is saved."
                )
                output = st.empty()
                chunks = ""
                stream = service.stream(scope, attempt.id)
                try:
                    for chunk in stream:
                        chunks += chunk
                        output.markdown(chunks)
                finally:
                    stream.close()
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
