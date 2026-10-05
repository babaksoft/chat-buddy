"""Focused Ongoing navigation and conversation page."""

from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import (
    Continuity,
    ContinuityGroup,
    ContinuityLifecycle,
    Identity,
    Persona,
)
from chat_buddy.characters.infrastructure import create_ongoing_services
from chat_buddy.characters.ui.new_ongoing_page import render_new_ongoing
from chat_buddy.characters.ui.ongoing import render_ongoing

_SCOPE_KEY = "characters_continuity_scope"


def render_ongoing_page() -> None:
    """Render ownership-scoped Ongoing navigation and the selected chat."""

    st.title("💞 Ongoing")
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
    """Render the complete hierarchy and an ownership-checked selection.

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
    groups = continuities.list_grouped()
    with st.sidebar:
        _render_hierarchy(identity_rows, persona_rows, groups, continuities)

    selected = _selected_continuity(groups, continuities)
    if selected is None:
        if not persona_rows:
            st.info("Create a persona before starting an Ongoing.")
        else:
            st.info(
                "Select an Ongoing from the sidebar, or choose a pair to start one."
            )
        return

    identity = next(row for row in identity_rows if row.id == selected.identity_id)
    persona = next(row for row in persona_rows if row.id == selected.persona_id)
    st.subheader(f"{identity.details.name} and {persona.core.name}")
    st.caption(f"Ongoing · {selected.lifecycle.value.capitalize()} · {selected.id}")
    _show_fields(selected.relationship.model_dump(mode="json", exclude={"origins"}))

    if selected.lifecycle == ContinuityLifecycle.ARCHIVED:
        st.info("Archived history is read-only. Profiles remain permanently frozen.")
    elif st.button("Archive Ongoing", key="characters_archive"):
        continuities.archive(
            selected.identity_id,
            selected.persona_id,
            selected.id,
        )
        st.rerun()

    render_ongoing(selected)


def _render_hierarchy(
    identities: list[Identity],
    personas: list[Persona],
    groups: tuple[ContinuityGroup, ...],
    service: ContinuityService,
) -> None:
    """Render every profile pair and its active and archived history.

    Args:
        identities:
            Persisted identity snapshots.
        personas:
            Persisted persona snapshots.
        groups:
            Existing continuities grouped by complete ownership.
        service:
            Continuity lifecycle operations.
    """

    st.header("Identity → Persona → Ongoing")
    grouped = {
        (group.identity_id, group.persona_id): group.continuities for group in groups
    }
    for identity in identities:
        with st.expander(identity.details.name, expanded=len(identities) == 1):
            if not personas:
                st.caption("No personas yet")
                continue
            for persona in personas:
                st.markdown(f"**{persona.core.name}**")
                rows = grouped.get((identity.id, persona.id), ())
                for continuity in rows:
                    label = (
                        f"{continuity.lifecycle.value.capitalize()} Ongoing · "
                        f"{str(continuity.id)[:8]}"
                    )
                    if st.button(
                        label,
                        key=f"characters_select_{continuity.id}",
                        use_container_width=True,
                    ):
                        _store_scope(identity.id, persona.id, continuity.id)
                        st.rerun()
                availability = service.start_availability(identity.id, persona.id)
                if st.button(
                    "New Ongoing",
                    key=f"characters_new_ongoing_{identity.id}_{persona.id}",
                    disabled=not availability.can_start,
                    help=availability.reason,
                    use_container_width=True,
                ):
                    _prepare_start(identity.id, persona.id)
                if availability.reason is not None:
                    st.caption(availability.reason)


def _selected_continuity(
    groups: tuple[ContinuityGroup, ...], service: ContinuityService
) -> Continuity | None:
    """Validate session scope against navigation before resuming it.

    Args:
        groups:
            Current ownership-grouped continuities.
        service:
            Continuity lifecycle operations.

    Returns:
        Ownership-checked selected continuity, or no selection.
    """

    scope = st.session_state.get(_SCOPE_KEY)
    if not (
        isinstance(scope, tuple)
        and len(scope) == 3
        and all(isinstance(identifier, UUID) for identifier in scope)
    ):
        return None
    identity_id, persona_id, continuity_id = scope
    valid = any(
        group.identity_id == identity_id
        and group.persona_id == persona_id
        and any(row.id == continuity_id for row in group.continuities)
        for group in groups
    )
    if not valid:
        st.session_state.pop(_SCOPE_KEY, None)
        st.session_state.pop("characters_continuity_id", None)
        return None
    return service.resume(identity_id, persona_id, continuity_id)


def _store_scope(identity_id: UUID, persona_id: UUID, continuity_id: UUID) -> None:
    """Store a complete selected continuity scope atomically.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
        continuity_id:
            Selected continuity.
    """

    st.session_state[_SCOPE_KEY] = (identity_id, persona_id, continuity_id)
    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    st.session_state["characters_continuity_id"] = continuity_id


def _prepare_start(identity_id: UUID, persona_id: UUID) -> None:
    """Retain a valid pair and open the dedicated start workflow.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
    """

    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    st.session_state.pop("characters_new_ongoing_identity", None)
    st.session_state.pop("characters_new_ongoing_persona", None)
    _navigate_to_new_ongoing()


def _navigate_to_new_ongoing() -> None:
    """Navigate to the dedicated Ongoing definition page."""

    st.switch_page(
        st.Page(
            render_new_ongoing,
            title="New Ongoing",
            icon="✨",
            url_path="new-ongoing",
        )
    )


def _show_fields(fields: dict[str, object]) -> None:
    """Present starting relationship values with readable labels.

    Args:
        fields:
            Starting-state fields without internal provenance.
    """

    for name, value in fields.items():
        if isinstance(value, list):
            display = ", ".join(str(item).replace("_", " ") for item in value) or "None"
        else:
            display = str(value)
        st.text(f"{name.replace('_', ' ').capitalize()}: {display}")
