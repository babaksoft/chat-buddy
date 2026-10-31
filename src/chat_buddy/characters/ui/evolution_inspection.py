"""Shared qualitative evolution inspection and correction panel."""

from __future__ import annotations

from enum import StrEnum
from typing import cast

import streamlit as st
from pydantic import TypeAdapter

from chat_buddy.characters.application import (
    EvolutionEventInspection,
    EvolutionInspection,
    EvolutionInspectionService,
)
from chat_buddy.characters.domain import (
    ContinuityLifecycle,
    EvolutionCommand,
    EvolutionCorrectionAction,
    EvolutionCorrectionConflictError,
    EvolutionEvent,
    EvolutionRejectionReason,
    EvolutionScope,
    RecordRelationshipMilestoneCommand,
    RelationshipMilestone,
    RelationshipRomanticStatus,
    RemovePersonaAdaptationCommand,
    SetAffectionCommand,
    SetDynamicCommand,
    SetPersonaAdaptationCommand,
    SetRomanticStatusCommand,
    SetSocialStatusCommand,
    SetTrustCommand,
    StartingRelationship,
)

_EVOLUTION_COMMAND_ADAPTER: TypeAdapter[EvolutionCommand] = TypeAdapter(
    EvolutionCommand
)


def render_evolution_inspection(
    service: EvolutionInspectionService,
    scope: EvolutionScope,
    starting_relationship: StartingRelationship,
    lifecycle: ContinuityLifecycle,
) -> None:
    """Render qualitative state, provenance, diagnostics, and corrections.

    Args:
        service:
            Inspection and guarded correction application operations.
        scope:
            Selected continuity ownership.
        starting_relationship:
            User-selected state from which evolution replays.
        lifecycle:
            Current continuity lifecycle controlling write availability.
    """

    try:
        inspection = service.inspect(scope, starting_relationship)
    except (LookupError, ValueError) as error:
        st.warning(f"Evolution state is unavailable: {error}")
        return

    with st.expander("Relationship evolution"):
        st.caption(
            "Qualitative continuity state. Inferences and corrections never edit "
            "conversation history or the authored persona."
        )
        _render_starting_state(inspection)
        _render_current_state(inspection)
        _render_event_history(service, inspection, lifecycle)
        _render_diagnostics(inspection)


def _render_starting_state(inspection: EvolutionInspection) -> None:
    """Render the explicitly user-selected replay baseline.

    Args:
        inspection:
            Complete evolution inspection view.
    """

    st.markdown("**User-selected starting state**")
    starting = inspection.starting_relationship
    _render_fields(
        {
            "Social": starting.social,
            "Romantic": starting.romantic,
            "Dynamic": starting.dynamic,
            "Trust": starting.trust,
            "Affection": starting.affection,
        }
    )


def _render_current_state(inspection: EvolutionInspection) -> None:
    """Render current relationship dimensions, adaptations, and milestones.

    Args:
        inspection:
            Complete evolution inspection view.
    """

    relationship = inspection.projections.relationship
    st.markdown("**Current state after replay**")
    _render_fields(
        {
            "Social": relationship.social,
            "Romantic": relationship.romantic,
            "Dynamic": relationship.dynamic,
            "Trust": relationship.trust,
            "Affection": relationship.affection,
        }
    )
    milestones = ", ".join(_label(item) for item in relationship.milestones)
    st.text(f"Milestones: {milestones or 'None'}")
    adaptations = inspection.projections.persona_adaptations.adaptations
    st.markdown("**Active persona adaptations**")
    if not adaptations:
        st.caption("No active adaptations")
    for adaptation in adaptations:
        st.text(f"{_label(adaptation.facet)}: {adaptation.value}")


def _render_event_history(
    service: EvolutionInspectionService,
    inspection: EvolutionInspection,
    lifecycle: ContinuityLifecycle,
) -> None:
    """Render inferred events with branch and user-correction dispositions.

    Args:
        service:
            Inspection and correction operations.
        inspection:
            State observed for presentation and optimistic correction guards.
        lifecycle:
            Current lifecycle controlling correction availability.
    """

    st.markdown("**Why this state exists**")
    if not inspection.events:
        st.caption("No inferred evolution events yet")
        return

    for item in inspection.events:
        status = _event_status(item)
        command = item.effective_command or item.event.command
        with st.expander(f"{_command_title(command)} · {status}"):
            st.caption(_status_explanation(item))
            st.write(f"Rationale: {command.rationale}")
            for position, evidence in enumerate(item.evidence, start=1):
                st.markdown(f"**Evidence {position}**")
                st.write(f"You: {evidence.user_content}")
                st.write(f"Persona: {evidence.persona_content}")
            if item.correction is not None:
                st.write(f"User correction note: {item.correction.note}")
            _render_event_diagnostics(item.event)
            if lifecycle == ContinuityLifecycle.ARCHIVED:
                st.caption("Archived continuities are read-only.")
            else:
                _render_correction_form(service, inspection, item)


def _render_event_diagnostics(event: EvolutionEvent) -> None:
    """Render exact strategy configuration for one accepted event.

    Args:
        event:
            Accepted immutable evolution event.
    """

    with st.expander("Diagnostic detail"):
        provenance = event.provenance
        st.text(f"Selector: {provenance.selector.name} {provenance.selector.version}")
        st.text(f"Strategy: {provenance.strategy.name} {provenance.strategy.version}")
        st.text(f"Policy: {provenance.policy.name} {provenance.policy.version}")
        st.text(
            f"Schema: {provenance.schema_identity.name} "
            f"{provenance.schema_identity.version}"
        )
        if provenance.provider is not None:
            st.text(f"Provider/model: {provenance.provider} / {provenance.model}")


def _render_correction_form(
    service: EvolutionInspectionService,
    inspection: EvolutionInspection,
    item: EvolutionEventInspection,
) -> None:
    """Render a confirmed correction, exclusion, or restoration form.

    Args:
        service:
            Guarded correction application operations.
        inspection:
            State observed before the user confirms a write.
        item:
            Inferred event and its current disposition.
    """

    correction = item.correction
    actions: tuple[str, ...]
    if (
        correction is not None
        and correction.action != EvolutionCorrectionAction.RESTORE
    ):
        actions = ("Restore inferred interpretation",)
    else:
        actions = ("Correct interpretation", "Exclude interpretation")
    key = f"characters_evolution_correction_{item.event.id}"
    with st.form(key):
        action = st.selectbox("Action", actions, key=f"{key}_action")
        replacement = None
        if action == "Correct interpretation":
            replacement = _replacement_input(item.event.command, key)
        note = st.text_area(
            "Reason",
            max_chars=1024,
            key=f"{key}_note",
            help="This note is retained as user-authored correction provenance.",
        )
        confirmed = st.checkbox(
            "Confirm this changes future relationship context",
            key=f"{key}_confirm",
        )
        submitted = st.form_submit_button(
            "Apply",
            disabled=(
                not confirmed
                or not note.strip()
                or (action == "Correct interpretation" and replacement is None)
            ),
        )
    if not submitted:
        return
    try:
        if action == "Exclude interpretation":
            service.exclude(inspection, item.event.id, note)
        elif action == "Restore inferred interpretation":
            service.restore(inspection, item.event.id, note)
        else:
            assert replacement is not None
            service.replace(inspection, item.event.id, replacement, note)
    except (EvolutionCorrectionConflictError, ValueError) as error:
        st.warning(f"Evolution state changed; review it and try again. {error}")
    else:
        st.rerun()


def _replacement_input(command: EvolutionCommand, key: str) -> EvolutionCommand | None:
    """Collect a same-target replacement while retaining exact evidence.

    Args:
        command:
            Original inferred command.
        key:
            Stable Streamlit widget-key prefix.

    Returns:
        Validated changed command, or None until the user changes its value.
    """

    if isinstance(command, SetPersonaAdaptationCommand):
        value = st.text_input(
            "Correct adaptation",
            value=command.value,
            max_chars=512,
            key=f"{key}_value",
        )
        if value == command.value or not value.strip():
            return None
        return _replace_command_fields(command, value=value)
    if isinstance(command, RemovePersonaAdaptationCommand):
        value = st.text_input(
            "Correct adaptation",
            value="",
            max_chars=512,
            key=f"{key}_value",
        )
        if not value.strip():
            return None
        return SetPersonaAdaptationCommand(
            facet=command.facet,
            expected=command.expected,
            value=value,
            rationale=command.rationale,
            sources=command.sources,
        )
    if isinstance(command, RecordRelationshipMilestoneCommand):
        milestone = cast(
            RelationshipMilestone,
            st.selectbox(
                "Correct milestone",
                tuple(RelationshipMilestone),
                index=tuple(RelationshipMilestone).index(command.milestone),
                format_func=_label,
                key=f"{key}_milestone",
            ),
        )
        value = _milestone_status(milestone, command, key)
        if milestone == command.milestone and value == command.value:
            return None
        return _replace_command_fields(command, milestone=milestone, value=value)

    value_type = type(command.value)
    values = tuple(value for value in value_type if value != command.expected)
    value = st.selectbox(
        "Correct value",
        values,
        index=values.index(command.value),
        format_func=_label,
        key=f"{key}_value",
    )
    if value == command.value:
        return None
    return _replace_command_fields(command, value=value)


def _milestone_status(
    milestone: RelationshipMilestone,
    command: RecordRelationshipMilestoneCommand,
    key: str,
) -> RelationshipRomanticStatus:
    """Resolve a valid status for a corrected milestone.

    Args:
        milestone:
            User-selected corrected milestone.
        command:
            Original inferred milestone command.
        key:
            Stable Streamlit widget-key prefix.

    Returns:
        Milestone-compatible resulting romantic status.
    """

    fixed = {
        RelationshipMilestone.PARTNERSHIP: RelationshipRomanticStatus.PARTNER,
        RelationshipMilestone.ENGAGEMENT: RelationshipRomanticStatus.ENGAGED,
        RelationshipMilestone.MARRIAGE: RelationshipRomanticStatus.SPOUSE,
        RelationshipMilestone.BREAKUP: RelationshipRomanticStatus.NONE,
    }
    if milestone in fixed:
        return fixed[milestone]
    values = tuple(
        value
        for value in RelationshipRomanticStatus
        if value not in (RelationshipRomanticStatus.NONE, command.expected)
    )
    return st.selectbox(
        "Reconciled status",
        values,
        format_func=_label,
        key=f"{key}_romantic_value",
    )


def _render_diagnostics(inspection: EvolutionInspection) -> None:
    """Render rejected proposals only when optional diagnostics are opened.

    Args:
        inspection:
            Complete inspection including rejected audit effects.
    """

    with st.expander("Rejected proposal diagnostics"):
        if not inspection.rejected_effects:
            st.caption("No rejected proposals")
            return
        for effect in inspection.rejected_effects:
            assert effect.decision is not None
            reason = cast(EvolutionRejectionReason, effect.decision.reason)
            st.markdown(f"**Rejected: {_label(reason)}**")
            st.caption(
                f"Strategy {effect.provenance.strategy.name} "
                f"{effect.provenance.strategy.version} · Policy "
                f"{effect.provenance.policy.name} {effect.provenance.policy.version}"
            )
            assert effect.proposal is not None
            for command in effect.proposal.commands:
                st.write(f"{_command_title(command)} — {command.rationale}")


def _replace_command_fields(
    command: EvolutionCommand, **updates: object
) -> EvolutionCommand:
    """Create a fully validated replacement command with retained provenance.

    Args:
        command:
            Original inferred command.
        **updates:
            Same-target user-authored field replacements.

    Returns:
        Validated replacement retaining original evidence and rationale.
    """

    payload = command.model_dump(mode="python")
    payload.update(updates)
    return _EVOLUTION_COMMAND_ADAPTER.validate_python(payload)


def _render_fields(fields: dict[str, object]) -> None:
    """Render qualitative labeled fields without numeric progress metaphors.

    Args:
        fields:
            Ordered display labels and qualitative values.
    """

    for name, value in fields.items():
        st.text(f"{name}: {_label(value)}")


def _event_status(item: EvolutionEventInspection) -> str:
    """Return the explicit provenance/disposition label for an event.

    Args:
        item:
            Inferred event with selected-history and correction state.

    Returns:
        Concise user-facing provenance and disposition label.
    """

    if not item.selected:
        suffix = ""
        if item.correction is not None:
            suffix = f" · user-{item.correction.action.value}"
        return f"Temporarily inactive (branch-derived){suffix}"
    if item.correction is None:
        return "Inferred evolution"
    if item.correction.action == EvolutionCorrectionAction.RESTORE:
        return "Inferred evolution · user-restored"
    if item.correction.action == EvolutionCorrectionAction.EXCLUDE:
        return "User-authored exclusion"
    return "User-authored correction"


def _status_explanation(item: EvolutionEventInspection) -> str:
    """Explain why the event currently is or is not replayed.

    Args:
        item:
            Inferred event with selected-history and correction state.

    Returns:
        Plain-language replay explanation.
    """

    if not item.selected:
        return (
            "Its cited exchange is not on the selected branch; the event is retained."
        )
    if item.effective_command is None:
        return "The original inference is retained for audit but excluded by the user."
    if (
        item.correction is not None
        and item.correction.action == EvolutionCorrectionAction.REPLACE
    ):
        return "The user's replacement is replayed instead of the original inference."
    return "This validated inference currently contributes to the projection."


def _command_title(command: EvolutionCommand) -> str:
    """Return a concise human-readable command summary.

    Args:
        command:
            Typed evolution command to summarize.

    Returns:
        Concise qualitative target label.
    """

    if isinstance(
        command, (SetPersonaAdaptationCommand, RemovePersonaAdaptationCommand)
    ):
        return f"Persona adaptation · {_label(command.facet)}"
    if isinstance(command, RecordRelationshipMilestoneCommand):
        return f"Milestone · {_label(command.milestone)}"
    names = {
        SetSocialStatusCommand: "Social status",
        SetRomanticStatusCommand: "Romantic status",
        SetDynamicCommand: "Interaction dynamic",
        SetTrustCommand: "Trust",
        SetAffectionCommand: "Affection",
    }
    return names[type(command)]


def _label(value: object) -> str:
    """Convert enum and stored values into readable qualitative labels.

    Args:
        value:
            Enum or stored scalar value.

    Returns:
        Capitalized label with machine separators removed.
    """

    raw = value.value if isinstance(value, StrEnum) else str(value)
    return raw.replace("_", " ").capitalize()
