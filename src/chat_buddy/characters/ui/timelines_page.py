"""Focused Timeline ownership, represented-day, and archive navigation."""

from uuid import UUID

import streamlit as st

from chat_buddy.characters.application import (
    ConversationService,
    IdentityService,
    PersonaService,
    TimelineDayService,
    TimelineService,
)
from chat_buddy.characters.domain import (
    ContinuityLifecycle,
    ContinuityMode,
    ConversationTarget,
    DayReservationStatus,
    EffectiveGeneration,
    EvolutionScope,
    Identity,
    Persona,
    SubmittedInput,
    Timeline,
    TimelineDay,
    TimelineGroup,
    TimelineNavigation,
    TimelineRevisionStatus,
)
from chat_buddy.characters.infrastructure import (
    create_continuity_memory_service,
    create_conversation_service,
    create_evolution_inspection_service,
    create_response_style_service,
    create_timeline_interaction_services,
    create_timeline_services,
)
from chat_buddy.characters.ui.evolution_inspection import render_evolution_inspection
from chat_buddy.characters.ui.ongoing import render_conversation, stream_attempt
from chat_buddy.characters.ui.response_style import render_response_style
from chat_buddy.characters.ui.storyline_memory import render_storyline_memory

_SCOPE_KEY = "characters_timeline_scope"
_DAY_KEY = "characters_timeline_day_id"


def render_timelines_page() -> None:
    """Render ownership-scoped Timeline and represented-day navigation."""

    st.title("🗓️ Timelines")
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
    """Render navigation and the selected Timeline.

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
    groups = timelines.list_grouped()
    with st.sidebar:
        _render_hierarchy(identity_rows, persona_rows, groups, timelines)
    navigation = _selected_navigation(groups, timelines)
    if navigation is None:
        if not persona_rows:
            st.info("Create a persona before starting a Timeline.")
        else:
            st.info(
                "Select a Timeline from the sidebar, or choose a pair to start one."
            )
        return
    identity = next(
        row for row in identity_rows if row.id == navigation.timeline.identity_id
    )
    persona = next(
        row for row in persona_rows if row.id == navigation.timeline.persona_id
    )
    _render_timeline(identity, persona, navigation, timelines)


def _render_hierarchy(
    identities: list[Identity],
    personas: list[Persona],
    groups: tuple[TimelineGroup, ...],
    service: TimelineService,
) -> None:
    """Render every pair with active and archived Timelines separated.

    Args:
        identities:
            Persisted identity snapshots.
        personas:
            Persisted persona snapshots.
        groups:
            Timelines grouped by complete ownership.
        service:
            Timeline lifecycle operations.
    """

    st.header("Identity → Persona → Timelines")
    grouped = {(row.identity_id, row.persona_id): row.timelines for row in groups}
    for identity in identities:
        with st.expander(identity.details.name, expanded=len(identities) == 1):
            if not personas:
                st.caption("No personas yet")
                continue
            for persona in personas:
                st.markdown(f"**{persona.core.name}**")
                rows = grouped.get((identity.id, persona.id), ())
                active = tuple(
                    row for row in rows if row.lifecycle == ContinuityLifecycle.ACTIVE
                )
                archived = tuple(
                    row for row in rows if row.lifecycle == ContinuityLifecycle.ARCHIVED
                )
                if active:
                    st.caption("Active")
                    _render_timeline_buttons(identity.id, persona.id, active)
                if archived:
                    st.caption("Archived")
                    _render_timeline_buttons(identity.id, persona.id, archived)
                availability = service.start_availability(identity.id, persona.id)
                if st.button(
                    "New Timeline",
                    key=f"characters_new_timeline_{identity.id}_{persona.id}",
                    disabled=not availability.can_start,
                    help=availability.reason,
                    use_container_width=True,
                ):
                    _prepare_start(identity.id, persona.id)
                if availability.reason is not None:
                    st.caption(availability.reason)


def _render_timeline_buttons(
    identity_id: UUID, persona_id: UUID, timelines: tuple[Timeline, ...]
) -> None:
    """Render selection buttons for one lifecycle group.

    Args:
        identity_id:
            Shared identity owner.
        persona_id:
            Shared persona owner.
        timelines:
            Timeline snapshots in the lifecycle group.
    """

    for timeline in timelines:
        if st.button(
            timeline.name,
            key=f"characters_select_timeline_{timeline.id}",
            use_container_width=True,
        ):
            _store_scope(identity_id, persona_id, timeline.id)
            st.rerun()


def _selected_navigation(
    groups: tuple[TimelineGroup, ...], service: TimelineService
) -> TimelineNavigation | None:
    """Validate stored ownership before resuming a Timeline.

    Args:
        groups:
            Current ownership-grouped Timelines.
        service:
            Timeline lifecycle operations.

    Returns:
        Owned navigation snapshot or no selection.
    """

    scope = st.session_state.get(_SCOPE_KEY)
    if not (
        isinstance(scope, tuple)
        and len(scope) == 3
        and all(isinstance(identifier, UUID) for identifier in scope)
    ):
        return None
    identity_id, persona_id, timeline_id = scope
    valid = any(
        group.identity_id == identity_id
        and group.persona_id == persona_id
        and any(row.id == timeline_id for row in group.timelines)
        for group in groups
    )
    if not valid:
        _clear_selection()
        return None
    return service.resume(identity_id, persona_id, timeline_id)


def _render_timeline(
    identity: Identity,
    persona: Persona,
    navigation: TimelineNavigation,
    service: TimelineService,
) -> None:
    """Render selected Timeline metadata, days, and archive action.

    Args:
        identity:
            Owning identity snapshot.
        persona:
            Owning persona snapshot.
        navigation:
            Current Timeline and represented days.
        service:
            Timeline lifecycle operations.
    """

    timeline = navigation.timeline
    st.subheader(timeline.name)
    st.caption(
        f"{identity.details.name} and {persona.core.name} · "
        f"{timeline.lifecycle.value.capitalize()} · "
        f"Calendar: {timeline.calendar_timezone.name}"
    )
    if timeline.lifecycle == ContinuityLifecycle.ARCHIVED:
        st.info("Archived Timelines and their represented days are read-only.")
    else:
        _render_archive(timeline, service)
    render_response_style(
        create_response_style_service(),
        timeline.id,
        f"characters_timeline_style_{timeline.id}",
        timeline.lifecycle == ContinuityLifecycle.ARCHIVED,
    )
    st.write("Days")
    selected_leaf_id = None
    if not navigation.days:
        st.info(
            "No days have been represented yet. A day appears with the first message "
            "sent on a local calendar date."
        )
        if timeline.lifecycle == ContinuityLifecycle.ACTIVE:
            _render_first_interaction(timeline)
    else:
        selected = _selected_day(navigation)
        for day in navigation.days:
            if st.button(
                _day_label(day, navigation),
                key=f"characters_select_timeline_day_{day.id}",
                type="primary" if day.id == selected.id else "secondary",
            ):
                st.session_state[_DAY_KEY] = day.id
                st.rerun()
        selected_leaf_id = _render_day(selected, navigation)
        if (
            selected.is_closed
            and selected.id == navigation.days[-1].id
            and timeline.lifecycle == ContinuityLifecycle.ACTIVE
        ):
            _render_first_interaction(timeline)

    render_storyline_memory(
        create_continuity_memory_service(),
        timeline,
        selected_leaf_id,
        mode_label="Timeline",
    )
    render_evolution_inspection(
        create_evolution_inspection_service(),
        EvolutionScope(
            identity_id=timeline.identity_id,
            persona_id=timeline.persona_id,
            continuity_id=timeline.id,
        ),
        timeline.relationship,
        timeline.lifecycle,
    )


def _render_archive(timeline: Timeline, service: TimelineService) -> None:
    """Render explicit confirmation for permanent Timeline archive.

    Args:
        timeline:
            Active Timeline snapshot.
        service:
            Timeline lifecycle operations.
    """

    with st.expander("Archive Timeline"):
        st.warning("Archiving is permanent. Existing days remain available read-only.")
        confirmed = st.checkbox(
            "I understand this Timeline cannot be resumed for new messages.",
            key=f"characters_archive_timeline_confirm_{timeline.id}",
        )
        if st.button(
            "Archive Timeline",
            key=f"characters_archive_timeline_{timeline.id}",
            disabled=not confirmed,
        ):
            result = service.archive(
                timeline.identity_id,
                timeline.persona_id,
                timeline.id,
                timeline.revision,
            )
            if result.status == TimelineRevisionStatus.STALE_REVISION:
                st.warning(
                    "The Timeline changed. Review the latest version and try again."
                )
            else:
                st.rerun()


def _selected_day(navigation: TimelineNavigation) -> TimelineDay:
    """Resolve an owned selected day, defaulting to the latest represented day.

    Args:
        navigation:
            Current owned Timeline navigation.

    Returns:
        Selected represented day.
    """

    selected_id = st.session_state.get(_DAY_KEY)
    selected = next((day for day in navigation.days if day.id == selected_id), None)
    if selected is None:
        selected = navigation.days[-1]
        st.session_state[_DAY_KEY] = selected.id
    return selected


def _day_label(day: TimelineDay, navigation: TimelineNavigation) -> str:
    """Build a date and application-derived state label.

    Args:
        day:
            Represented day snapshot.
        navigation:
            Owning Timeline navigation.

    Returns:
        Human-readable stable day label.
    """

    state = "closed" if day.is_closed else "current · open"
    if (
        navigation.timeline.lifecycle == ContinuityLifecycle.ARCHIVED
        and not day.is_closed
    ):
        state = "archived · read-only"
    return f"{day.boundary.local_date.isoformat()} · {state}"


def _render_day(day: TimelineDay, navigation: TimelineNavigation) -> UUID | None:
    """Render one represented day's immutable calendar status and conversation.

    Args:
        day:
            Selected represented day.
        navigation:
            Owning Timeline navigation.

    Returns:
        Selected persona leaf identifier, when the day graph is nonempty.
    """

    st.subheader(day.boundary.local_date.isoformat())
    if day.is_closed:
        st.info("This represented day is closed and permanently read-only.")
    elif navigation.timeline.lifecycle == ContinuityLifecycle.ARCHIVED:
        st.info("This represented day is read-only because its Timeline is archived.")
    else:
        st.success("This is the current open represented day.")
    target = ConversationTarget(
        scope=day.scope,
        mode=ContinuityMode.TIMELINE,
        entry_id=day.id,
    )
    read_only = day.is_closed or day.id != navigation.days[-1].id
    reason = None
    if day.is_closed:
        reason = (
            "This day is permanently closed. Retry, alternative selection, and "
            "Branch from here are unavailable for every historical message."
        )
    elif day.id != navigation.days[-1].id:
        reason = (
            "Only the latest open day can change. Historical graph actions are "
            "unavailable."
        )
    return render_conversation(
        create_conversation_service(),
        target,
        f"characters_timeline_day_{day.id}",
        navigation.timeline.lifecycle == ContinuityLifecycle.ARCHIVED,
        read_only=read_only,
        read_only_reason=reason,
    )


def _render_first_interaction(timeline: Timeline) -> None:
    """Reserve and stream the first interaction for the current local day.

    Args:
        timeline:
            Active Timeline accepting a possible new represented day.
    """

    st.info(
        "Sending the first message represents the current local calendar day. "
        "Earlier days remain permanently read-only; merely viewing this page "
        "creates nothing."
    )
    submitted = st.chat_input(
        "Start today's Timeline day",
        key=f"characters_timeline_first_input_{timeline.id}_{timeline.revision}",
    )
    if not submitted:
        return
    days, conversations, generation = create_timeline_interaction_services()
    _reserve_first_interaction(days, conversations, generation, timeline, submitted)


def _reserve_first_interaction(
    days: TimelineDayService,
    conversations: ConversationService,
    generation: EffectiveGeneration,
    timeline: Timeline,
    content: str,
) -> None:
    """Handle one explicit atomic day reservation outcome.

    Args:
        days:
            Clock-driven atomic day reservation service.
        conversations:
            Timeline-aware streaming service.
        generation:
            Effective default generation for the first attempt.
        timeline:
            Active owning Timeline.
        content:
            Validated user-authored first message.
    """

    result = days.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content=content),
        generation,
    )
    if result.status == DayReservationStatus.REUSED_OPEN_DAY:
        st.info("Today's open day already exists. Reloading it now.")
        st.rerun()
    if result.status != DayReservationStatus.RESERVED:
        _reservation_failure(result.status)
        return
    if result.day is None or result.attempt is None:
        raise ValueError("A successful Timeline reservation is incomplete")
    target = ConversationTarget(
        scope=result.day.scope,
        mode=ContinuityMode.TIMELINE,
        entry_id=result.day.id,
    )
    with st.chat_message("user"):
        st.markdown(content)
    stream_attempt(conversations, target, result.attempt)
    st.session_state[_DAY_KEY] = result.day.id
    st.rerun()


def _reservation_failure(status: DayReservationStatus) -> None:
    """Explain a failed atomic day reservation without retrying a stale write.

    Args:
        status:
            Stable application-level reservation outcome.
    """

    guidance = {
        DayReservationStatus.ARCHIVED: "This Timeline was archived and is read-only.",
        DayReservationStatus.CLOCK_MOVED_BACKWARD: (
            "The current clock contradicts saved day boundaries. Check the system "
            "clock before trying again."
        ),
        DayReservationStatus.DAY_CLOSED: (
            "The day closed while the message was being reserved. Reload and try "
            "again on the current day."
        ),
        DayReservationStatus.OPEN_ATTEMPT: (
            "A response attempt is already active. Reload its saved progress."
        ),
    }
    st.warning(
        guidance.get(
            status,
            "Timeline state changed while reserving the day. Reload and review it "
            "before sending again.",
        )
    )


def _prepare_start(identity_id: UUID, persona_id: UUID) -> None:
    """Retain the selected pair and navigate to Timeline creation.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
    """

    st.session_state["characters_identity_id"] = identity_id
    st.session_state["characters_persona_id"] = persona_id
    from chat_buddy.characters.ui.new_timeline_page import render_new_timeline

    st.switch_page(
        st.Page(
            render_new_timeline,
            title="New Timeline",
            icon="✨",
            url_path="new-timeline",
        )
    )


def _store_scope(identity_id: UUID, persona_id: UUID, timeline_id: UUID) -> None:
    """Store complete Timeline ownership and clear any prior day selection.

    Args:
        identity_id:
            Selected identity owner.
        persona_id:
            Selected persona owner.
        timeline_id:
            Selected Timeline.
    """

    st.session_state[_SCOPE_KEY] = (identity_id, persona_id, timeline_id)
    st.session_state.pop(_DAY_KEY, None)


def _clear_selection() -> None:
    """Clear invalid Timeline and represented-day selection state."""

    st.session_state.pop(_SCOPE_KEY, None)
    st.session_state.pop(_DAY_KEY, None)
