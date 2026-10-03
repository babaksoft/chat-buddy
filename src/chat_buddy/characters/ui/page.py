"""Profile management and deliberate Ongoing lifecycle navigation."""

from datetime import date
from typing import get_args
from uuid import UUID, uuid4

import streamlit as st

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import (
    Affection,
    Boundary,
    ContinuityLifecycle,
    Dynamic,
    Identity,
    IdentityDetails,
    Persona,
    PersonaCore,
    RelationshipIntent,
    RelationshipSelection,
    RomanticStatus,
    SocialStatus,
    StaleIdentityError,
    StalePersonaError,
    StartContinuity,
    Trust,
)
from chat_buddy.characters.infrastructure import create_profile_services


def render() -> None:
    """Render profile management and scoped lifecycle selection lazily."""

    st.title("👥 Characters")
    identities, personas, continuities = create_profile_services()
    try:
        identities.ensure_default()
        _render_profiles(identities, personas, continuities)
    except (ValueError, LookupError) as error:
        st.error(str(error))


def _render_profiles(
    identities: IdentityService,
    personas: PersonaService,
    continuities: ContinuityService,
) -> None:
    """Select owners and render their editors and Ongoing history.

    Args:
        identities:
            Identity application operations.
        personas:
            Persona application operations.
        continuities:
            Ownership-scoped lifecycle operations.
    """

    identity_rows = identities.list()
    persona_rows = personas.list()
    with st.sidebar:
        st.header("Identity → Persona → Ongoing")
        identity_id = _select_owner(
            "identity", {row.id: row.details.name for row in identity_rows}
        )
        persona_id = _select_owner(
            "persona", {row.id: row.core.name for row in persona_rows}
        )
        for group in continuities.list_grouped():
            if (group.identity_id, group.persona_id) != (identity_id, persona_id):
                continue
            for row in group.continuities:
                if st.button(
                    f"Ongoing · {row.lifecycle.value} · {str(row.id)[:8]}",
                    key=f"characters_select_{row.id}",
                ):
                    st.session_state["characters_continuity_id"] = row.id
    identity = next(row for row in identity_rows if row.id == identity_id)
    persona = next((row for row in persona_rows if row.id == persona_id), None)
    st.caption(
        f"Identity: {identity.details.name} · "
        f"Persona: {persona.core.name if persona else 'None selected'} · Mode: Ongoing"
    )
    with st.expander("Identity profiles"):
        _identity_editor(identities, None)
        _identity_editor(identities, identity)
    with st.expander("Persona profiles", expanded=persona is None):
        _persona_editor(personas, None)
        if persona is not None:
            _persona_editor(personas, persona)
    if persona is None:
        st.info("Create a persona to review an Ongoing start.")
        return
    _render_start(identity, persona, continuities)
    selected = st.session_state.get("characters_continuity_id")
    rows = [
        row
        for group in continuities.list_grouped()
        if (group.identity_id, group.persona_id) == (identity.id, persona.id)
        for row in group.continuities
    ]
    if selected not in {row.id for row in rows}:
        return
    continuity = continuities.resume(identity.id, persona.id, selected)
    st.subheader(f"Ongoing · {continuity.lifecycle.value}")
    st.caption(f"Continuity: {continuity.id}")
    _show_fields(continuity.relationship.model_dump(mode="json", exclude={"origins"}))
    if continuity.lifecycle == ContinuityLifecycle.ARCHIVED:
        st.info("Archived history is read-only. Profiles remain permanently frozen.")
    elif st.button("Archive Ongoing", key="characters_archive"):
        continuities.archive(identity.id, persona.id, continuity.id)
        st.rerun()


def _select_owner(kind: str, labels: dict[UUID, str]) -> UUID | None:
    """Keep owner selection across page switches using a durable session key.

    Args:
        kind:
            Profile kind for namespaced widgets.
        labels:
            Stable identifiers and display labels.

    Returns:
        The selected owner, or None when no profiles exist.
    """

    saved = f"characters_{kind}_id"
    options = list(labels)
    previous = st.session_state.get(saved)
    selected = st.selectbox(
        kind.title(),
        options,
        index=options.index(previous) if previous in options else 0,
        format_func=lambda identifier: labels[identifier],
        key=f"characters_{kind}_widget",
    )
    st.session_state[saved] = selected
    return selected


def _identity_editor(service: IdentityService, profile: Identity | None) -> None:
    """Create or replace all authored identity fields, or duplicate a profile.

    Args:
        service:
            Identity management service.
        profile:
            Existing snapshot, or None for creation.
    """

    key = (
        f"characters_identity_{profile.id}_{profile.revision}"
        if profile
        else "characters_identity_new"
    )
    details = profile.details if profile else IdentityDetails(name="You")
    frozen = profile is not None and profile.is_frozen
    if frozen:
        st.info("Identity is frozen. Duplicate it to make authored changes.")
    with st.form(key):
        name = st.text_input(
            "Identity name",
            value=details.name if profile else "",
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
        save = st.form_submit_button(
            "Save identity" if profile else "Create identity",
            disabled=frozen,
            key=f"{key}_save",
        )
    if save:
        replacement = IdentityDetails(
            name=name,
            gender=gender or None,
            age=int(age) if age else None,
            birth_date=date.fromisoformat(birth) if birth else None,
            pronouns=pronouns or None,
            preferred_address=address or None,
            timezone=timezone or None,
        )
        saved = (
            service.edit(profile.id, replacement, profile.revision)
            if profile
            else service.create(replacement)
        )
        st.session_state["characters_identity_id"] = saved.id
        st.session_state.pop("characters_identity_widget", None)
        st.rerun()
    if profile and st.button(
        "Duplicate identity", key=f"characters_duplicate_identity_{profile.id}"
    ):
        duplicate = service.duplicate(profile.id)
        st.session_state["characters_identity_id"] = duplicate.id
        st.session_state.pop("characters_identity_widget", None)
        st.rerun()


def _persona_editor(service: PersonaService, profile: Persona | None) -> None:
    """Create or replace a persona core and offer independent duplication.

    Args:
        service:
            Persona management service.
        profile:
            Existing snapshot, or None for creation.
    """

    key = (
        f"characters_persona_{profile.id}_{profile.revision}"
        if profile
        else "characters_persona_new"
    )
    frozen = profile is not None and profile.is_frozen
    if frozen:
        st.info("Persona is frozen globally. Duplicate it to make authored changes.")
    with st.form(key):
        name = st.text_input(
            "Persona name",
            value=profile.core.name if profile else "",
            max_chars=128,
            key=f"{key}_name",
        )
        definition = st.text_area(
            "Definition",
            value=profile.core.definition if profile else "",
            max_chars=8192,
            key=f"{key}_definition",
        )
        traits = st.text_area(
            "Traits (optional)",
            value=(profile.core.traits or "") if profile else "",
            max_chars=4096,
            key=f"{key}_traits",
        )
        save = st.form_submit_button(
            "Save persona" if profile else "Create persona",
            disabled=frozen,
            key=f"{key}_save",
        )
    if save:
        core = PersonaCore(name=name, definition=definition, traits=traits or None)
        saved = (
            service.edit(profile.id, core, profile.revision)
            if profile
            else service.create(core)
        )
        st.session_state["characters_persona_id"] = saved.id
        st.session_state.pop("characters_persona_widget", None)
        st.rerun()
    if profile and st.button(
        "Duplicate persona", key=f"characters_duplicate_persona_{profile.id}"
    ):
        duplicate = service.duplicate(profile.id)
        st.session_state["characters_persona_id"] = duplicate.id
        st.session_state.pop("characters_persona_widget", None)
        st.rerun()


def _render_start(
    identity: Identity, persona: Persona, service: ContinuityService
) -> None:
    """Review an immutable start request and submit only explicit confirmation.

    Args:
        identity:
            Selected identity snapshot.
        persona:
            Selected persona snapshot.
        service:
            Continuity lifecycle service.
    """

    st.subheader("Start Ongoing")
    st.write(
        "A new Ongoing carries forward only the selected authored profiles and a fresh starting relationship. It has its own conversation and rolling summary, with no extracted memory or inherited shared events."
    )
    with st.form("characters_start_form"):
        st.selectbox("Mode", ["Ongoing"], key="characters_mode")
        intent = st.selectbox(
            "Relationship intent",
            list(RelationshipIntent),
            format_func=lambda value: value.value.replace("_", " ").capitalize(),
            key="characters_intent",
        )
        st.caption(
            "Established relationships require explicit social and romantic statuses."
        )
        fields = {
            "social": st.selectbox(
                "Social status",
                [None, *get_args(SocialStatus)],
                key="characters_social",
            ),
            "romantic": st.selectbox(
                "Romantic status",
                [None, *get_args(RomanticStatus)],
                key="characters_romantic",
            ),
            "dynamic": st.selectbox(
                "Current dynamic", [None, *get_args(Dynamic)], key="characters_dynamic"
            ),
            "trust": st.selectbox(
                "Trust", [None, *get_args(Trust)], key="characters_trust"
            ),
            "affection": st.selectbox(
                "Affection", [None, *get_args(Affection)], key="characters_affection"
            ),
        }
        boundaries = st.multiselect(
            "Boundaries", get_args(Boundary), key="characters_boundaries"
        )
        review = st.form_submit_button("Review start", key="characters_review_start")
    if review:
        st.session_state.pop("characters_review", None)
        relationship = RelationshipSelection.model_validate(
            {
                "intent": intent,
                **fields,
                "boundaries": tuple(boundaries) if boundaries else None,
            }
        )
        st.session_state["characters_review"] = (
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
    reviewed = st.session_state.get("characters_review")
    if reviewed is None:
        return
    request, reviewed_identity, reviewed_persona = reviewed
    if (request.identity_id, request.persona_id) != (identity.id, persona.id):
        st.info(
            "A start is awaiting review for another profile pair. Select that pair or review a new start."
        )
        return
    if (request.identity_revision, request.persona_revision) != (
        identity.revision,
        persona.revision,
    ):
        st.session_state.pop("characters_review", None)
        st.warning(
            "Profiles changed after review. Review the start again before confirming."
        )
        return
    st.subheader("Confirm reviewed start")
    st.write(
        "Confirmation permanently freezes every authored field on both profiles. Later authored changes require duplication. Duplicates carry only authored fields, without history or relationship state."
    )
    st.write("Reviewed identity")
    _show_fields(reviewed_identity.details.model_dump(mode="json", exclude_none=True))
    st.write("Reviewed persona")
    _show_fields(reviewed_persona.core.model_dump(mode="json", exclude_none=True))
    st.write("Reviewed relationship · Ongoing")
    _show_fields(request.relationship.model_dump(mode="json", exclude_none=True))
    st.caption(
        "Omitted starting fields default to stranger, no romance, neutral dynamic, unknown trust, neutral affection, and no boundaries."
    )
    if st.button("Cancel start", key="characters_cancel_start"):
        st.session_state.pop("characters_review", None)
        st.rerun()
    if st.button("Confirm start", key="characters_confirm_start"):
        try:
            continuity = service.start(request)
        except (StaleIdentityError, StalePersonaError):
            st.session_state.pop("characters_review", None)
            st.warning(
                "Profiles changed after review. Review the start again before confirming."
            )
            return
        st.session_state["characters_continuity_id"] = continuity.id
        st.session_state.pop("characters_review", None)
        st.rerun()


def _show_fields(fields: dict[str, object]) -> None:
    """Present authored and relationship values with readable field labels.

    Args:
        fields:
            Authored or starting-state fields without internal provenance.
    """

    for name, value in fields.items():
        if isinstance(value, list):
            display = ", ".join(str(item).replace("_", " ") for item in value) or "None"
        else:
            display = str(value)
        st.text(f"{name.replace('_', ' ').capitalize()}: {display}")
