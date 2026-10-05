"""Focused persona management page."""

from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import PersonaService
from chat_buddy.characters.domain import Persona, PersonaCore
from chat_buddy.characters.infrastructure import create_persona_service


def render_personas() -> None:
    """Render persona creation, selection, editing, and duplication."""

    st.title("🎭 Personas")
    st.caption("Manage who you talk with in Characters.")
    service = create_persona_service()
    try:
        _render_management(service)
    except (ValueError, LookupError) as error:
        st.error(str(error))


def _render_management(service: PersonaService) -> None:
    """Render the persona list beside the active persona form.

    Args:
        service:
            Persona application operations.
    """

    personas = service.list()
    selected_id = _selected_persona_id(personas)
    list_column, editor_column = st.columns((1, 2), gap="large")
    with list_column:
        st.subheader("Existing personas")
        if st.button(
            "New persona",
            key="characters_persona_new_action",
            type="primary",
            use_container_width=True,
        ):
            st.session_state["characters_persona_creating"] = True

        for persona in personas:
            status = "Frozen" if persona.is_frozen else "Editable"
            if st.button(
                persona.core.name,
                key=f"characters_persona_manage_{persona.id}",
                type="primary" if persona.id == selected_id else "secondary",
                use_container_width=True,
            ):
                st.session_state["characters_persona_id"] = persona.id
                st.session_state["characters_persona_creating"] = False
                st.rerun()

            st.caption(f"{_definition_excerpt(persona)}  \n{status}")
    with editor_column:
        if st.session_state.get("characters_persona_creating", not personas):
            st.subheader("Create persona")
            _persona_form(service, None)
            return

        selected = next(persona for persona in personas if persona.id == selected_id)
        st.subheader(selected.core.name)
        _persona_form(service, selected)


def _selected_persona_id(personas: list[Persona]) -> UUID | None:
    """Resolve and retain a valid persona selection.

    Args:
        personas:
            Persisted personas in deterministic order.

    Returns:
        Selected persona identifier, or None when no personas exist.
    """

    if not personas:
        st.session_state["characters_persona_creating"] = True
        return None

    selected = st.session_state.get("characters_persona_id")
    valid_ids = {persona.id for persona in personas}
    if selected not in valid_ids:
        selected = personas[0].id
        st.session_state["characters_persona_id"] = selected

    return selected


def _persona_form(service: PersonaService, persona: Persona | None) -> None:
    """Create, edit, or duplicate a persona from one complete form.

    Args:
        service:
            Persona application operations.
        persona:
            Selected persisted persona, or None during creation.
    """

    core = persona.core if persona is not None else None
    frozen = persona is not None and persona.is_frozen
    if frozen:
        st.info(
            "This persona was used to start an Ongoing, so changing it would "
            "rewrite that history. Duplicate it to make changes."
        )
    key = (
        f"characters_persona_management_{persona.id}_{persona.revision}"
        if persona is not None
        else "characters_persona_management_new"
    )

    with st.form(key):
        name = st.text_input(
            "Persona name",
            value=core.name if core is not None else "",
            max_chars=128,
            key=f"{key}_name",
        )
        definition = st.text_area(
            "Definition",
            value=core.definition if core is not None else "",
            max_chars=8192,
            key=f"{key}_definition",
        )
        traits = st.text_area(
            "Traits (optional)",
            value=(core.traits or "") if core is not None else "",
            max_chars=4096,
            key=f"{key}_traits",
        )
        label = (
            "Create persona"
            if persona is None
            else "Duplicate persona" if frozen else "Save changes"
        )
        submitted = st.form_submit_button(label, type="primary")

    if not submitted:
        return
    replacement = PersonaCore(
        name=name,
        definition=definition,
        traits=traits or None,
    )

    if persona is None:
        saved = service.create(replacement)
    elif frozen:
        saved = service.duplicate(persona.id, replacement)
    else:
        saved = service.edit(persona.id, replacement, persona.revision)

    st.session_state["characters_persona_id"] = saved.id
    st.session_state["characters_persona_creating"] = False
    st.rerun()


def _definition_excerpt(persona: Persona) -> str:
    """Create a concise single-line excerpt of the authored definition.

    Args:
        persona:
            Persisted persona snapshot to summarize.

    Returns:
        Whitespace-normalized definition capped at 96 characters.
    """

    definition = " ".join(persona.core.definition.split())
    return definition if len(definition) <= 96 else f"{definition[:93].rstrip()}..."
