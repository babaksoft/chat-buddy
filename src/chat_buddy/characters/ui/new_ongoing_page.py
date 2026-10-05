"""Dedicated definition and preview workflow for starting an Ongoing."""

from typing import get_args
from uuid import UUID, uuid4

import streamlit as st

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import (
    ActiveContinuityError,
    Affection,
    Boundary,
    Dynamic,
    Identity,
    Persona,
    RelationshipIntent,
    RelationshipSelection,
    RomanticStatus,
    SocialStatus,
    StaleIdentityError,
    StalePersonaError,
    StartContinuity,
    Trust,
)
from chat_buddy.characters.infrastructure import create_ongoing_services

_REVIEW_KEY = "characters_new_ongoing_review"
_DRAFT_KEYS = (
    "characters_new_ongoing_intent",
    "characters_new_ongoing_social",
    "characters_new_ongoing_romantic",
    "characters_new_ongoing_dynamic",
    "characters_new_ongoing_trust",
    "characters_new_ongoing_affection",
    "characters_new_ongoing_boundaries",
)


def render_new_ongoing() -> None:
    """Render the dedicated definition and review workflow."""

    st.title("✨ New Ongoing")
    identities, personas, continuities = create_ongoing_services()
    try:
        identities.ensure_default()
        _render_page(identities, personas, continuities)
    except (ValueError, LookupError) as error:
        st.error(str(error))


def _render_page(
    identities: IdentityService,
    personas: PersonaService,
    continuities: ContinuityService,
) -> None:
    """Render the current start workflow state.

    Args:
        identities:
            Identity application operations.
        personas:
            Persona application operations.
        continuities:
            Continuity lifecycle operations.
    """

    identity_rows = identities.list()
    persona_rows = personas.list()
    if not persona_rows:
        st.info("Create a persona before starting an Ongoing.")
        if st.button("Cancel", key="characters_new_ongoing_cancel_empty"):
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
            _restore_draft(request.relationship)
            st.session_state.pop(_REVIEW_KEY, None)
            st.warning(
                "Profiles changed after preview. Review the Ongoing again before confirming."
            )
        else:
            _render_preview(
                request,
                reviewed_identity,
                reviewed_persona,
                continuities,
            )
            return

    identity = _select_profile(
        "identity", identity_rows, {row.id: row.details.name for row in identity_rows}
    )
    persona = _select_profile(
        "persona", persona_rows, {row.id: row.core.name for row in persona_rows}
    )
    _render_definition(identity, persona, continuities)


def _select_profile(
    kind: str,
    profiles: list[Identity] | list[Persona],
    labels: dict[UUID, str],
) -> Identity | Persona:
    """Select a profile while preserving the application-wide owner choice.

    Args:
        kind:
            Profile kind used for state keys and the visible label.
        profiles:
            Available profile snapshots.
        labels:
            Display labels keyed by stable identifier.

    Returns:
        The selected profile snapshot.
    """

    saved_key = f"characters_{kind}_id"
    widget_key = f"characters_new_ongoing_{kind}"
    options = list(labels)
    previous = st.session_state.get(saved_key)
    selected_id = st.selectbox(
        kind.title(),
        options,
        index=options.index(previous) if previous in options else 0,
        format_func=lambda identifier: labels[identifier],
        key=widget_key,
    )
    st.session_state[saved_key] = selected_id
    return next(profile for profile in profiles if profile.id == selected_id)


def _render_definition(
    identity: Identity | Persona,
    persona: Identity | Persona,
    service: ContinuityService,
) -> None:
    """Render draft inputs and create an immutable preview request.

    Args:
        identity:
            Selected identity snapshot.
        persona:
            Selected persona snapshot.
        service:
            Continuity lifecycle operations.
    """

    if not isinstance(identity, Identity) or not isinstance(persona, Persona):
        raise TypeError("New Ongoing profile selections have invalid types")

    st.subheader("Define Ongoing")
    st.caption(f"{identity.details.name} and {persona.core.name} · Ongoing")
    st.write(
        "Choose the starting relationship. The preview does not write data or freeze profiles."
    )
    availability = service.start_availability(identity.id, persona.id)
    if availability.reason is not None:
        st.info(availability.reason)
    with st.form("characters_new_ongoing_form"):
        intent = st.selectbox(
            "Relationship intent",
            list(RelationshipIntent),
            format_func=lambda value: value.value.replace("_", " ").capitalize(),
            key="characters_new_ongoing_intent",
        )
        st.caption(
            "Established relationships require explicit social and romantic statuses."
        )
        social = st.selectbox(
            "Social status",
            [None, *get_args(SocialStatus)],
            key="characters_new_ongoing_social",
        )
        romantic = st.selectbox(
            "Romantic status",
            [None, *get_args(RomanticStatus)],
            key="characters_new_ongoing_romantic",
        )
        dynamic = st.selectbox(
            "Current dynamic",
            [None, *get_args(Dynamic)],
            key="characters_new_ongoing_dynamic",
        )
        trust = st.selectbox(
            "Trust", [None, *get_args(Trust)], key="characters_new_ongoing_trust"
        )
        affection = st.selectbox(
            "Affection",
            [None, *get_args(Affection)],
            key="characters_new_ongoing_affection",
        )
        boundaries = st.multiselect(
            "Boundaries",
            get_args(Boundary),
            key="characters_new_ongoing_boundaries",
        )
        preview = st.form_submit_button(
            "Preview Ongoing",
            disabled=not availability.can_start,
            key="characters_new_ongoing_preview",
        )
    if preview:
        if not isinstance(intent, RelationshipIntent):
            raise TypeError("Relationship intent selection is required")
        relationship = RelationshipSelection(
            intent=intent,
            social=social,
            romantic=romantic,
            dynamic=dynamic,
            trust=trust,
            affection=affection,
            boundaries=tuple(boundaries) if boundaries else None,
        )
        st.session_state[_REVIEW_KEY] = (
            StartContinuity(
                request_id=uuid4(),
                identity_id=identity.id,
                persona_id=persona.id,
                identity_revision=identity.revision,
                persona_revision=persona.revision,
                relationship=relationship,
            ),
            identity,
            persona,
        )
        st.rerun()
    if st.button("Cancel", key="characters_new_ongoing_cancel_define"):
        _cancel()


def _render_preview(
    request: StartContinuity,
    identity: Identity,
    persona: Persona,
    service: ContinuityService,
) -> None:
    """Render a revision-bound preview and confirm it atomically.

    Args:
        request:
            Immutable reviewed start request.
        identity:
            Reviewed identity snapshot.
        persona:
            Reviewed persona snapshot.
        service:
            Continuity lifecycle operations.
    """

    st.subheader("Preview Ongoing")
    availability = service.start_availability(request.identity_id, request.persona_id)
    if availability.reason is not None:
        st.warning(availability.reason)
    st.write(
        "Confirmation permanently freezes both profiles. Later authored changes require independent duplicates."
    )
    st.write("Identity")
    _show_fields(identity.details.model_dump(mode="json", exclude_none=True))
    st.write("Persona")
    _show_fields(persona.core.model_dump(mode="json", exclude_none=True))
    st.write("Starting relationship · Ongoing")
    _show_fields(request.relationship.model_dump(mode="json", exclude_none=True))
    st.caption(
        "Omitted fields default to stranger, no romance, neutral dynamic, unknown trust, neutral affection, and no boundaries."
    )
    if st.button("Edit definition", key="characters_new_ongoing_edit"):
        _restore_draft(request.relationship)
        st.session_state.pop(_REVIEW_KEY, None)
        st.rerun()
    if st.button("Cancel", key="characters_new_ongoing_cancel_preview"):
        _cancel()
    if st.button(
        "Confirm Ongoing",
        key="characters_new_ongoing_confirm",
        disabled=not availability.can_start,
    ):
        try:
            continuity = service.start(request)
        except (StaleIdentityError, StalePersonaError):
            _restore_draft(request.relationship)
            st.session_state.pop(_REVIEW_KEY, None)
            st.warning(
                "Profiles changed after preview. Review the Ongoing again before confirming."
            )
            return
        except ActiveContinuityError as error:
            st.error(str(error))
            return
        st.session_state["characters_identity_id"] = continuity.identity_id
        st.session_state["characters_persona_id"] = continuity.persona_id
        st.session_state["characters_continuity_id"] = continuity.id
        st.session_state["characters_continuity_scope"] = (
            continuity.identity_id,
            continuity.persona_id,
            continuity.id,
        )
        _clear_workflow()
        _navigate_to_ongoing()


def _cancel() -> None:
    """Discard the workflow without changing the selected Ongoing scope."""

    _clear_workflow()
    _navigate_to_ongoing()


def _clear_workflow() -> None:
    """Remove the pending review and relationship draft fields."""

    st.session_state.pop(_REVIEW_KEY, None)
    for key in _DRAFT_KEYS:
        st.session_state.pop(key, None)


def _restore_draft(relationship: RelationshipSelection) -> None:
    """Restore reviewed values after preview widgets leave the render tree.

    Args:
        relationship:
            Relationship draft retained by the immutable review request.
    """

    st.session_state["characters_new_ongoing_intent"] = relationship.intent
    st.session_state["characters_new_ongoing_social"] = relationship.social
    st.session_state["characters_new_ongoing_romantic"] = relationship.romantic
    st.session_state["characters_new_ongoing_dynamic"] = relationship.dynamic
    st.session_state["characters_new_ongoing_trust"] = relationship.trust
    st.session_state["characters_new_ongoing_affection"] = relationship.affection
    st.session_state["characters_new_ongoing_boundaries"] = list(
        relationship.boundaries or ()
    )


def _navigate_to_ongoing() -> None:
    """Navigate to the focused Ongoing history page."""

    from chat_buddy.characters.ui.ongoing_page import render_ongoing_page

    st.switch_page(
        st.Page(
            render_ongoing_page,
            title="Ongoing",
            icon="💞",
            url_path="ongoing",
        )
    )


def _show_fields(fields: dict[str, object]) -> None:
    """Present reviewed profile and relationship fields.

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
