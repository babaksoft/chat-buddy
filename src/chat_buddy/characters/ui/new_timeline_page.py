"""Dedicated reviewed workflow for starting a Timeline."""

from typing import get_args
from uuid import UUID, uuid4

import streamlit as st
from pydantic import ValidationError

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    TimelineService,
    default_response_style,
)
from chat_buddy.characters.domain import (
    Affection,
    Boundary,
    ConfirmationConflictError,
    ContinuityMode,
    Dynamic,
    Identity,
    Persona,
    RelationshipIntent,
    RelationshipSelection,
    RomanticStatus,
    SocialStatus,
    StaleIdentityError,
    StalePersonaError,
    TimelineStartReview,
    TimelineStartStatus,
    Trust,
)
from chat_buddy.characters.infrastructure import create_timeline_services

_REVIEW_KEY = "characters_new_timeline_review"
_DRAFT_KEYS = (
    "characters_new_timeline_name",
    "characters_new_timeline_intent",
    "characters_new_timeline_social",
    "characters_new_timeline_romantic",
    "characters_new_timeline_dynamic",
    "characters_new_timeline_trust",
    "characters_new_timeline_affection",
    "characters_new_timeline_boundaries",
)


def render_new_timeline() -> None:
    """Render the reviewed Timeline start workflow."""

    st.title("✨ New Timeline")
    identities, personas, timelines = create_timeline_services()
    try:
        identities.ensure_default()
        _render_page(identities, personas, timelines)
    except (ValueError, LookupError) as error:
        st.error(str(error))


def _render_page(
    identities: IdentityService,
    personas: PersonaService,
    timelines: TimelineService,
) -> None:
    """Render the current definition or review state.

    Args:
        identities:
            Identity application operations.
        personas:
            Persona application operations.
        timelines:
            Timeline lifecycle operations.
    """

    identity_rows = identities.list()
    persona_rows = personas.list()
    if not persona_rows:
        st.info("Create a persona before starting a Timeline.")
        if st.button("Cancel", key="characters_new_timeline_cancel_empty"):
            _cancel()
        return

    reviewed = st.session_state.get(_REVIEW_KEY)
    if reviewed is not None:
        request, reviewed_identity, reviewed_persona = reviewed
        current_identity = next(
            (row for row in identity_rows if row.id == request.identity_id), None
        )
        current_persona = next(
            (row for row in persona_rows if row.id == request.persona_id), None
        )
        if (
            current_identity is None
            or current_persona is None
            or current_identity.revision != request.identity_revision
            or current_persona.revision != request.persona_revision
        ):
            _restore_draft(request)
            st.session_state.pop(_REVIEW_KEY, None)
            st.warning(
                "Profiles changed after preview. Review the Timeline again before confirming."
            )
        else:
            _render_preview(request, reviewed_identity, reviewed_persona, timelines)
            return

    identity = _select_profile(
        "identity", identity_rows, {row.id: row.details.name for row in identity_rows}
    )
    persona = _select_profile(
        "persona", persona_rows, {row.id: row.core.name for row in persona_rows}
    )
    _render_definition(identity, persona, timelines)


def _select_profile(
    kind: str,
    profiles: list[Identity] | list[Persona],
    labels: dict[UUID, str],
) -> Identity | Persona:
    """Select one profile while retaining the shared owner choice.

    Args:
        kind:
            Profile kind used in labels and state keys.
        profiles:
            Available profile snapshots.
        labels:
            Display labels keyed by stable identifier.

    Returns:
        Selected profile snapshot.
    """

    saved_key = f"characters_{kind}_id"
    options = list(labels)
    previous = st.session_state.get(saved_key)
    selected_id = st.selectbox(
        kind.title(),
        options,
        index=options.index(previous) if previous in options else 0,
        format_func=lambda identifier: labels[identifier],
        key=f"characters_new_timeline_{kind}",
    )
    st.session_state[saved_key] = selected_id
    return next(profile for profile in profiles if profile.id == selected_id)


def _render_definition(
    identity: Identity | Persona,
    persona: Identity | Persona,
    service: TimelineService,
) -> None:
    """Render definition fields and prepare an immutable review.

    Args:
        identity:
            Selected identity snapshot.
        persona:
            Selected persona snapshot.
        service:
            Timeline lifecycle operations.
    """

    if not isinstance(identity, Identity) or not isinstance(persona, Persona):
        raise TypeError("New Timeline profile selections have invalid types")
    st.subheader("Define Timeline")
    st.caption(f"{identity.details.name} and {persona.core.name} · Timeline")
    availability = service.start_availability(identity.id, persona.id)
    if availability.reason is not None:
        st.info(availability.reason)
    with st.form("characters_new_timeline_form"):
        name = st.text_input(
            "Timeline name", max_chars=128, key="characters_new_timeline_name"
        )
        intent = st.selectbox(
            "Relationship intent",
            list(RelationshipIntent),
            format_func=lambda value: value.value.replace("_", " ").capitalize(),
            key="characters_new_timeline_intent",
        )
        social = st.selectbox(
            "Social status",
            [None, *get_args(SocialStatus)],
            key="characters_new_timeline_social",
        )
        romantic = st.selectbox(
            "Romantic status",
            [None, *get_args(RomanticStatus)],
            key="characters_new_timeline_romantic",
        )
        dynamic = st.selectbox(
            "Current dynamic",
            [None, *get_args(Dynamic)],
            key="characters_new_timeline_dynamic",
        )
        trust = st.selectbox(
            "Trust", [None, *get_args(Trust)], key="characters_new_timeline_trust"
        )
        affection = st.selectbox(
            "Affection",
            [None, *get_args(Affection)],
            key="characters_new_timeline_affection",
        )
        boundaries = st.multiselect(
            "Boundaries",
            get_args(Boundary),
            key="characters_new_timeline_boundaries",
        )
        preview = st.form_submit_button(
            "Preview Timeline",
            disabled=not availability.can_start,
            key="characters_new_timeline_preview",
        )
    if preview:
        if not isinstance(intent, RelationshipIntent):
            raise TypeError("Relationship intent selection is required")
        try:
            request = TimelineStartReview(
                request_id=uuid4(),
                identity_id=identity.id,
                persona_id=persona.id,
                identity_revision=identity.revision,
                persona_revision=persona.revision,
                name=name,
                relationship=RelationshipSelection(
                    intent=intent,
                    social=social,
                    romantic=romantic,
                    dynamic=dynamic,
                    trust=trust,
                    affection=affection,
                    boundaries=tuple(boundaries) if boundaries else None,
                ),
                response_style=default_response_style(ContinuityMode.TIMELINE),
            )
        except ValidationError as error:
            st.error(error.errors()[0]["msg"])
        else:
            st.session_state[_REVIEW_KEY] = (request, identity, persona)
            st.rerun()
    if st.button("Cancel", key="characters_new_timeline_cancel_define"):
        _cancel()


def _render_preview(
    request: TimelineStartReview,
    identity: Identity,
    persona: Persona,
    service: TimelineService,
) -> None:
    """Render and confirm one revision-bound Timeline preview.

    Args:
        request:
            Complete reviewed start request.
        identity:
            Reviewed identity snapshot.
        persona:
            Reviewed persona snapshot.
        service:
            Timeline lifecycle operations.
    """

    st.subheader("Preview Timeline")
    availability = service.start_availability(request.identity_id, request.persona_id)
    if availability.reason is not None:
        st.warning(availability.reason)
    st.write(f"Timeline: {request.name}")
    st.write("Identity")
    _show_fields(identity.details.model_dump(mode="json", exclude_none=True))
    st.write("Persona")
    _show_fields(persona.core.model_dump(mode="json", exclude_none=True))
    st.write("Starting relationship · Timeline")
    _show_fields(request.relationship.model_dump(mode="json", exclude_none=True))
    st.caption(
        "The application captures its local calendar when you confirm. "
        "The first day is created only when you send the first message."
    )
    if st.button("Edit definition", key="characters_new_timeline_edit"):
        _restore_draft(request)
        st.session_state.pop(_REVIEW_KEY, None)
        st.rerun()
    if st.button("Cancel", key="characters_new_timeline_cancel_preview"):
        _cancel()
    if st.button(
        "Confirm Timeline",
        key="characters_new_timeline_confirm",
        disabled=not availability.can_start,
    ):
        try:
            result = service.start(request)
        except (StaleIdentityError, StalePersonaError):
            _restore_draft(request)
            st.session_state.pop(_REVIEW_KEY, None)
            st.warning(
                "Profiles changed after preview. Review the Timeline again before confirming."
            )
            return
        except ConfirmationConflictError as error:
            st.error(str(error))
            return
        if result.status == TimelineStartStatus.ACTIVE_SLOT_CONFLICT:
            st.error("Archive the active Timeline before starting another.")
            return
        if result.timeline is None:
            raise RuntimeError("Successful Timeline start did not return a Timeline")
        _store_scope(
            result.timeline.identity_id,
            result.timeline.persona_id,
            result.timeline.id,
        )
        _clear_workflow()
        _navigate_to_timelines()


def _store_scope(identity_id: UUID, persona_id: UUID, timeline_id: UUID) -> None:
    """Store complete Timeline ownership after confirmation.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
        timeline_id:
            Selected Timeline.
    """

    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    st.session_state["characters_timeline_scope"] = (
        identity_id,
        persona_id,
        timeline_id,
    )


def _cancel() -> None:
    """Discard the workflow and return to Timeline navigation."""

    _clear_workflow()
    _navigate_to_timelines()


def _clear_workflow() -> None:
    """Remove the pending review and Timeline draft fields."""

    st.session_state.pop(_REVIEW_KEY, None)
    for key in _DRAFT_KEYS:
        st.session_state.pop(key, None)


def _restore_draft(request: TimelineStartReview) -> None:
    """Restore a reviewed request to definition widgets.

    Args:
        request:
            Reviewed request whose authored values should be restored.
    """

    st.session_state["characters_new_timeline_name"] = request.name
    relationship = request.relationship
    st.session_state["characters_new_timeline_intent"] = relationship.intent
    st.session_state["characters_new_timeline_social"] = relationship.social
    st.session_state["characters_new_timeline_romantic"] = relationship.romantic
    st.session_state["characters_new_timeline_dynamic"] = relationship.dynamic
    st.session_state["characters_new_timeline_trust"] = relationship.trust
    st.session_state["characters_new_timeline_affection"] = relationship.affection
    st.session_state["characters_new_timeline_boundaries"] = list(
        relationship.boundaries or ()
    )


def _navigate_to_timelines() -> None:
    """Navigate to focused Timeline history."""

    from chat_buddy.characters.ui.timelines_page import render_timelines_page

    st.switch_page(
        st.Page(
            render_timelines_page,
            title="Timelines",
            icon="🗓️",
            url_path="timelines",
        )
    )


def _show_fields(fields: dict[str, object]) -> None:
    """Present reviewed values with readable labels.

    Args:
        fields:
            Reviewed values without internal provenance.
    """

    for name, value in fields.items():
        if isinstance(value, list):
            display = ", ".join(str(item).replace("_", " ") for item in value) or "None"
        else:
            display = str(value)
        st.text(f"{name.replace('_', ' ').capitalize()}: {display}")
