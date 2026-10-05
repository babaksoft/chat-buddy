"""Focused identity management page."""

from datetime import date
from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import IdentityService
from chat_buddy.characters.domain import Identity, IdentityDetails
from chat_buddy.characters.infrastructure import create_identity_service


def render_identities() -> None:
    """Render identity creation, selection, editing, and duplication."""

    st.title("🪪 Identities")
    st.caption("Manage who you are in Characters.")
    service = create_identity_service()
    try:
        service.ensure_default()
        _render_management(service)
    except (ValueError, LookupError) as error:
        st.error(str(error))


def _render_management(service: IdentityService) -> None:
    """Render the identity list beside the active identity form.

    Args:
        service:
            Identity application operations.
    """

    identities = service.list()
    selected_id = _selected_identity_id(identities)
    list_column, editor_column = st.columns((1, 2), gap="large")
    with list_column:
        st.subheader("Existing identities")
        if st.button(
            "New identity",
            key="characters_identity_new_action",
            type="primary",
            use_container_width=True,
        ):
            st.session_state["characters_identity_creating"] = True
        for identity in identities:
            status = "Frozen" if identity.is_frozen else "Editable"
            default = " · Default" if identity.is_default else ""
            if st.button(
                identity.details.name,
                key=f"characters_identity_manage_{identity.id}",
                type="primary" if identity.id == selected_id else "secondary",
                use_container_width=True,
            ):
                st.session_state["characters_identity_id"] = identity.id
                st.session_state["characters_identity_creating"] = False
                st.rerun()
            st.caption(f"{_identity_summary(identity)}  \n{status}{default}")
    with editor_column:
        if st.session_state.get("characters_identity_creating", False):
            st.subheader("Create identity")
            _identity_form(service, None)
            return
        selected = next(
            identity for identity in identities if identity.id == selected_id
        )
        st.subheader(selected.details.name)
        _identity_form(service, selected)


def _selected_identity_id(identities: list[Identity]) -> UUID:
    """Resolve and retain a valid identity selection.

    Args:
        identities:
            Default-first persisted identities.

    Returns:
        Selected identity identifier.
    """

    selected = st.session_state.get("characters_identity_id")
    valid_ids = {identity.id for identity in identities}
    if selected not in valid_ids:
        selected = identities[0].id
        st.session_state["characters_identity_id"] = selected
    return selected


def _identity_form(service: IdentityService, identity: Identity | None) -> None:
    """Create, edit, or duplicate an identity from one complete form.

    Args:
        service:
            Identity application operations.
        identity:
            Selected persisted identity, or None during creation.
    """

    details = identity.details if identity is not None else IdentityDetails(name="You")
    frozen = identity is not None and identity.is_frozen
    if frozen:
        st.info(
            "This identity was used to start an Ongoing, so changing it would "
            "rewrite that history. Duplicate it to make changes."
        )
    key = (
        f"characters_identity_management_{identity.id}_{identity.revision}"
        if identity is not None
        else "characters_identity_management_new"
    )
    with st.form(key):
        name = st.text_input(
            "Identity name",
            value=details.name if identity is not None else "",
            max_chars=128,
            key=f"{key}_name",
        )
        gender = st.text_input(
            "Gender (optional)",
            value=details.gender or "",
            max_chars=64,
            key=f"{key}_gender",
        )
        age = st.text_input(
            "Age (optional)",
            value=str(details.age) if details.age is not None else "",
            key=f"{key}_age",
        )
        birth = st.text_input(
            "Birth date (optional, YYYY-MM-DD)",
            value=details.birth_date.isoformat() if details.birth_date else "",
            key=f"{key}_birth_date",
        )
        pronouns = st.text_input(
            "Pronouns (optional)",
            value=details.pronouns or "",
            max_chars=64,
            key=f"{key}_pronouns",
        )
        address = st.text_input(
            "Preferred address (optional)",
            value=details.preferred_address or "",
            max_chars=128,
            key=f"{key}_address",
        )
        timezone = st.text_input(
            "IANA timezone (optional)",
            value=details.timezone or "",
            max_chars=64,
            key=f"{key}_timezone",
        )
        label = (
            "Create identity"
            if identity is None
            else "Duplicate identity" if frozen else "Save changes"
        )
        submitted = st.form_submit_button(label, type="primary")
    if not submitted:
        return
    replacement = IdentityDetails(
        name=name,
        gender=gender or None,
        age=int(age) if age else None,
        birth_date=date.fromisoformat(birth) if birth else None,
        pronouns=pronouns or None,
        preferred_address=address or None,
        timezone=timezone or None,
    )
    if identity is None:
        saved = service.create(replacement)
    elif frozen:
        saved = service.duplicate(identity.id, replacement)
    else:
        saved = service.edit(identity.id, replacement, identity.revision)
    st.session_state["characters_identity_id"] = saved.id
    st.session_state["characters_identity_creating"] = False
    st.rerun()


def _identity_summary(identity: Identity) -> str:
    """Create a compact summary using only persisted authored attributes.

    Args:
        identity:
            Persisted identity snapshot to summarize.

    Returns:
        Human-readable populated attributes or an explicit empty summary.
    """

    details = identity.details
    parts = [
        details.preferred_address,
        details.pronouns,
        details.gender,
        f"Age {details.age}" if details.age is not None else None,
        details.birth_date.isoformat() if details.birth_date is not None else None,
        details.timezone,
    ]
    return " · ".join(part for part in parts if part) or "No additional details"
