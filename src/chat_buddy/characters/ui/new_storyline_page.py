"""Dedicated reviewed workflow for starting a Storyline."""

from typing import get_args
from uuid import UUID, uuid4

import streamlit as st

from chat_buddy.characters.application import (
    IdentityService,
    PersonaService,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ActiveStorylineError,
    Affection,
    Boundary,
    Dynamic,
    Identity,
    Persona,
    RelationshipIntent,
    RelationshipSelection,
    ResponseStyleSnapshot,
    RomanticStatus,
    SceneDetails,
    SocialStatus,
    StaleIdentityError,
    StalePersonaError,
    StartStoryline,
    Trust,
)
from chat_buddy.characters.infrastructure import create_storyline_services

_REVIEW_KEY = "characters_new_storyline_review"
_STYLE = ResponseStyleSnapshot(
    name="storyline.default",
    version="1.0.0",
    instruction="Respond naturally within the current scene.",
)
_DRAFT_KEYS = (
    "characters_new_storyline_name",
    "characters_new_storyline_scene_title",
    "characters_new_storyline_scene_setup",
    "characters_new_storyline_intent",
    "characters_new_storyline_social",
    "characters_new_storyline_romantic",
    "characters_new_storyline_dynamic",
    "characters_new_storyline_trust",
    "characters_new_storyline_affection",
    "characters_new_storyline_boundaries",
)


def render_new_storyline() -> None:
    """Render the dedicated Storyline definition and review workflow."""

    st.title("✨ New Storyline")
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
    """Render the current workflow state.

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
    if not persona_rows:
        st.info("Create a persona before starting a Storyline.")
        if st.button("Cancel", key="characters_new_storyline_cancel_empty"):
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
                "Profiles changed after preview. Review the Storyline again before confirming."
            )
        else:
            _render_preview(request, reviewed_identity, reviewed_persona, storylines)
            return

    identity = _select_profile(
        "identity", identity_rows, {row.id: row.details.name for row in identity_rows}
    )
    persona = _select_profile(
        "persona", persona_rows, {row.id: row.core.name for row in persona_rows}
    )
    _render_definition(identity, persona, storylines)


def _select_profile(
    kind: str,
    profiles: list[Identity] | list[Persona],
    labels: dict[UUID, str],
) -> Identity | Persona:
    """Select a profile while preserving the shared owner choice.

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
    widget_key = f"characters_new_storyline_{kind}"
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
    service: StorylineService,
) -> None:
    """Render draft fields and create an immutable review request.

    Args:
        identity:
            Selected identity snapshot.
        persona:
            Selected persona snapshot.
        service:
            Storyline lifecycle operations.
    """

    if not isinstance(identity, Identity) or not isinstance(persona, Persona):
        raise TypeError("New Storyline profile selections have invalid types")

    st.subheader("Define Storyline")
    st.caption(f"{identity.details.name} and {persona.core.name} · Storyline")
    availability = service.start_availability(identity.id, persona.id)
    if availability.reason is not None:
        st.info(availability.reason)
    with st.form("characters_new_storyline_form"):
        name = st.text_input(
            "Storyline name", max_chars=128, key="characters_new_storyline_name"
        )
        title = st.text_input(
            "Initial scene title",
            max_chars=128,
            key="characters_new_storyline_scene_title",
        )
        setup = st.text_area(
            "Initial scene setup",
            max_chars=8192,
            key="characters_new_storyline_scene_setup",
        )
        intent = st.selectbox(
            "Relationship intent",
            list(RelationshipIntent),
            format_func=lambda value: value.value.replace("_", " ").capitalize(),
            key="characters_new_storyline_intent",
        )
        social = st.selectbox(
            "Social status",
            [None, *get_args(SocialStatus)],
            key="characters_new_storyline_social",
        )
        romantic = st.selectbox(
            "Romantic status",
            [None, *get_args(RomanticStatus)],
            key="characters_new_storyline_romantic",
        )
        dynamic = st.selectbox(
            "Current dynamic",
            [None, *get_args(Dynamic)],
            key="characters_new_storyline_dynamic",
        )
        trust = st.selectbox(
            "Trust", [None, *get_args(Trust)], key="characters_new_storyline_trust"
        )
        affection = st.selectbox(
            "Affection",
            [None, *get_args(Affection)],
            key="characters_new_storyline_affection",
        )
        boundaries = st.multiselect(
            "Boundaries",
            get_args(Boundary),
            key="characters_new_storyline_boundaries",
        )
        preview = st.form_submit_button(
            "Preview Storyline",
            disabled=not availability.can_start,
            key="characters_new_storyline_preview",
        )
    if preview:
        if not isinstance(intent, RelationshipIntent):
            raise TypeError("Relationship intent selection is required")
        request = StartStoryline(
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
            initial_scene=SceneDetails(title=title, setup=setup, response_style=_STYLE),
        )
        st.session_state[_REVIEW_KEY] = (request, identity, persona)
        st.rerun()
    if st.button("Cancel", key="characters_new_storyline_cancel_define"):
        _cancel()


def _render_preview(
    request: StartStoryline,
    identity: Identity,
    persona: Persona,
    service: StorylineService,
) -> None:
    """Render and commit one revision-bound Storyline preview.

    Args:
        request:
            Immutable reviewed start request.
        identity:
            Reviewed identity snapshot.
        persona:
            Reviewed persona snapshot.
        service:
            Storyline lifecycle operations.
    """

    st.subheader("Preview Storyline")
    availability = service.start_availability(request.identity_id, request.persona_id)
    if availability.reason is not None:
        st.warning(availability.reason)
    st.write(f"Storyline: {request.name}")
    st.write(f"Initial scene: {request.initial_scene.title}")
    st.write(request.initial_scene.setup)
    st.write("Identity")
    _show_fields(identity.details.model_dump(mode="json", exclude_none=True))
    st.write("Persona")
    _show_fields(persona.core.model_dump(mode="json", exclude_none=True))
    st.write("Starting relationship · Storyline")
    _show_fields(request.relationship.model_dump(mode="json", exclude_none=True))
    st.caption(
        "Confirmation freezes both profiles and fixes the response style for this scene."
    )
    if st.button("Edit definition", key="characters_new_storyline_edit"):
        _restore_draft(request)
        st.session_state.pop(_REVIEW_KEY, None)
        st.rerun()
    if st.button("Cancel", key="characters_new_storyline_cancel_preview"):
        _cancel()
    if st.button(
        "Confirm Storyline",
        key="characters_new_storyline_confirm",
        disabled=not availability.can_start,
    ):
        try:
            storyline, scene = service.start(request)
        except (StaleIdentityError, StalePersonaError):
            _restore_draft(request)
            st.session_state.pop(_REVIEW_KEY, None)
            st.warning(
                "Profiles changed after preview. Review the Storyline again before confirming."
            )
            return
        except ActiveStorylineError as error:
            st.error(str(error))
            return
        _store_scope(
            storyline.identity_id, storyline.persona_id, storyline.id, scene.id
        )
        _clear_workflow()
        _navigate_to_storylines()


def _store_scope(
    identity_id: UUID, persona_id: UUID, storyline_id: UUID, scene_id: UUID
) -> None:
    """Store complete Storyline and scene ownership after confirmation.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
        storyline_id:
            Selected Storyline.
        scene_id:
            Selected initial scene.
    """

    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    st.session_state["characters_storyline_id"] = storyline_id
    st.session_state["characters_storyline_scope"] = (
        identity_id,
        persona_id,
        storyline_id,
    )
    st.session_state["characters_scene_id"] = scene_id


def _cancel() -> None:
    """Discard the workflow and return to Storyline navigation."""

    _clear_workflow()
    _navigate_to_storylines()


def _clear_workflow() -> None:
    """Remove the pending review and all Storyline draft fields."""

    st.session_state.pop(_REVIEW_KEY, None)
    for key in _DRAFT_KEYS:
        st.session_state.pop(key, None)


def _restore_draft(request: StartStoryline) -> None:
    """Restore a reviewed request to definition widgets.

    Args:
        request:
            Reviewed request whose authored values should be restored.
    """

    st.session_state["characters_new_storyline_name"] = request.name
    st.session_state["characters_new_storyline_scene_title"] = (
        request.initial_scene.title
    )
    st.session_state["characters_new_storyline_scene_setup"] = (
        request.initial_scene.setup
    )
    relationship = request.relationship
    st.session_state["characters_new_storyline_intent"] = relationship.intent
    st.session_state["characters_new_storyline_social"] = relationship.social
    st.session_state["characters_new_storyline_romantic"] = relationship.romantic
    st.session_state["characters_new_storyline_dynamic"] = relationship.dynamic
    st.session_state["characters_new_storyline_trust"] = relationship.trust
    st.session_state["characters_new_storyline_affection"] = relationship.affection
    st.session_state["characters_new_storyline_boundaries"] = list(
        relationship.boundaries or ()
    )


def _navigate_to_storylines() -> None:
    """Navigate to the focused Storyline history page."""

    from chat_buddy.characters.ui.storylines_page import render_storylines_page

    st.switch_page(
        st.Page(
            render_storylines_page,
            title="Storylines",
            icon="📚",
            url_path="storylines",
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
