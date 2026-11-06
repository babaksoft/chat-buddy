"""Open-day Timeline conversation, summary, and closure behavior."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ConversationService,
    ResponseStyleService,
    TimelineConversationAdapter,
    TimelineDayService,
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ContinuityMode,
    ConversationTarget,
    EffectiveGeneration,
    ModelDescriptor,
    PromptMessage,
    ProviderInvocationError,
    SubmittedInput,
    TimelineDayReadOnlyError,
    TimelineGraphActionUnavailableReason,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbResponseStyleRepository,
    DbSummaryRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)
from chat_buddy.characters.infrastructure.llm import ConfiguredModelRegistry
from tests.characters_support import FakeResponse
from tests.integration.characters.test_timeline_repositories import _request


class MutableClock:
    """Return one explicitly controlled aware UTC instant.

    Attributes:
        value:
            Current instant returned to application policy.
    """

    def __init__(self, value: datetime) -> None:
        """Initialize the clock.

        Args:
            value:
                Initial aware UTC instant.
        """

        self.value = value

    def now(self) -> datetime:
        """Return the configured instant.

        Returns:
            Current test instant.
        """

        return self.value


class MessageCountCounter:
    """Assign ten tokens to every provider message."""

    def count(self, messages: tuple[PromptMessage, ...]) -> int:
        """Return a deterministic framing-sensitive estimate.

        Args:
            messages:
                Complete provider input.

        Returns:
            Ten tokens per message.
        """

        return len(messages) * 10


class FakeSummary:
    """Capture summary calls and return deterministic revisions."""

    def __init__(self) -> None:
        """Initialize empty capture state."""

        self.captured: list[tuple[PromptMessage, ...]] = []

    def summarize(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> str:
        """Capture a request and return concise summary text.

        Args:
            messages:
                Bounded summary input.
            generation:
                Effective summary provenance.

        Returns:
            Deterministic revision content.
        """

        del generation
        self.captured.append(messages)
        return f"Timeline summary {len(self.captured)}"


class BoundaryCrossingResponse(FakeResponse):
    """Advance the injected clock after producing provider output."""

    def __init__(self, clock: MutableClock, closes_at: datetime) -> None:
        """Bind the clock and boundary crossed by the stream.

        Args:
            clock:
                Mutable injected clock.
            closes_at:
                Exact day closing instant.
        """

        super().__init__()
        self._clock = clock
        self._closes_at = closes_at

    def stream(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> Iterator[str]:
        """Yield output, then move the clock to the closing boundary.

        Args:
            messages:
                Assembled prompt.
            generation:
                Effective response provenance.

        Yields:
            One persisted output chunk.
        """

        self.captured.append(messages)
        self.generations.append(generation)
        yield "Too late"
        self._clock.value = self._closes_at


class ArchivingResponse(FakeResponse):
    """Archive the owning Timeline after producing provider output."""

    def __init__(
        self,
        timelines: DbTimelineRepository,
        identity_id: UUID,
        persona_id: UUID,
        timeline_id: UUID,
    ) -> None:
        """Bind the Timeline archived by the stream.

        Args:
            timelines:
                Timeline lifecycle repository.
            identity_id:
                Owning identity identifier.
            persona_id:
                Owning persona identifier.
            timeline_id:
                Timeline identifier.
        """

        super().__init__()
        self._timelines = timelines
        self._identity_id = identity_id
        self._persona_id = persona_id
        self._timeline_id = timeline_id

    def stream(
        self, messages: tuple[PromptMessage, ...], generation: EffectiveGeneration
    ) -> Iterator[str]:
        """Yield output, then archive before persona-message commit.

        Args:
            messages:
                Assembled prompt.
            generation:
                Effective response provenance.

        Yields:
            One persisted output chunk.
        """

        self.captured.append(messages)
        self.generations.append(generation)
        yield "Archived output"
        current = self._timelines.get(
            self._identity_id, self._persona_id, self._timeline_id
        )
        self._timelines.archive(
            self._identity_id,
            self._persona_id,
            self._timeline_id,
            current.revision,
        )


def test_open_day_conversation_summarizes_and_survives_restart(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist attempts, style provenance, and compatible current-day summaries.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    summaries = FakeSummary()
    app, target = _start_day(factory, clock, responses, summaries, "First input")

    first_attempt = app.history(target).attempts[0]
    assert first_attempt.response_context is not None
    assert first_attempt.response_context.selector.name == (
        "baseline.timeline_response_context"
    )
    assert first_attempt.response_context.prompt_schema_version == "1.0.0"
    assert list(app.stream(target, first_attempt.id)) == ["Hello", " there"]
    first_node = DbConversationRepository(factory).graph(target.scope).nodes[-1]
    assert first_node.response_provenance is not None
    assert (
        first_node.response_provenance.response_style.source_revision
        == first_attempt.response_style.source_revision
    )
    assert (
        first_node.response_provenance.response_context
        == first_attempt.response_context
    )

    for content in ("Second input", "Third input", "Fourth input"):
        attempt = app.send(target, SubmittedInput(content=content))
        list(app.stream(target, attempt.id))

    active = DbSummaryRepository(factory).get_current(target.scope)
    assert active is not None
    assert active.content == "Timeline summary 2"
    assert len(summaries.captured) == 2

    old_leaf_id = app.history(target).messages[-1].id
    responses.chunks = ("Alternate fourth",)
    retry = app.retry_completed_response(target)
    list(app.stream(target, retry.id))
    new_leaf_id = app.history(target).messages[-1].id
    compatible_new = DbSummaryRepository(factory).get_current(target.scope)
    assert compatible_new is not None
    app.select_alternative(target, old_leaf_id, new_leaf_id)
    compatible_old = DbSummaryRepository(factory).get_current(target.scope)
    assert compatible_old is not None
    selected_ids = {
        node.id
        for node in DbConversationRepository(factory)
        .selected_path(target.scope)
        .messages
    }
    assert compatible_old.checkpoint_message_id in selected_ids

    responses.chunks = ("Hello", " there")
    restarted = _service(factory, clock, responses, summaries)
    fifth = restarted.send(target, SubmittedInput(content="Fifth input"))
    list(restarted.stream(target, fifth.id))
    assert restarted.history(target).messages[-1].content == "Hello there"
    assert any(
        message.content.startswith("Conversation summary:\nTimeline summary")
        for message in responses.captured[-1]
    )


def test_new_day_prompt_never_contains_prior_day_transcript(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep prior-day messages and summaries out of current-day short-term context.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    summaries = FakeSummary()
    app, first_target = _start_day(
        factory, clock, responses, summaries, "Prior day secret"
    )
    assert first_target.entry_id is not None
    first_attempt = app.history(first_target).attempts[0]
    list(app.stream(first_target, first_attempt.id))
    first_day = DbTimelineDayRepository(factory).get(
        first_target.scope, first_target.entry_id
    )

    clock.value = first_day.boundary.closes_at
    timelines = DbTimelineRepository(factory)
    timeline = timelines.get(
        first_target.scope.identity_id,
        first_target.scope.persona_id,
        first_target.scope.continuity_id,
    )
    days = TimelineDayService(
        timelines,
        DbTimelineDayRepository(factory),
        DbConversationRepository(factory),
        clock,
    )
    reserved = days.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="Current day only"),
        _registry(responses, summaries).resolve_default("response"),
    )
    assert reserved.day is not None
    assert reserved.attempt is not None
    second_target = first_target.model_copy(
        update={"scope": reserved.day.scope, "entry_id": reserved.day.id}
    )

    list(app.stream(second_target, reserved.attempt.id))
    rendered = "\n".join(message.content for message in responses.captured[-1])
    assert "Current day only" in rendered
    assert "Prior day secret" not in rendered
    assert first_target.scope.conversation_id != second_target.scope.conversation_id
    with pytest.raises(TimelineDayReadOnlyError):
        app.send(first_target, SubmittedInput(content="Backdated input"))


def test_stream_crossing_boundary_is_interrupted_without_persona_commit(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Observe closure immediately before commit and preserve partial evidence.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    initial = FakeResponse()
    summaries = FakeSummary()
    _, target = _start_day(factory, clock, initial, summaries, "Boundary input")
    assert target.entry_id is not None
    day = DbTimelineDayRepository(factory).get(target.scope, target.entry_id)
    crossing = BoundaryCrossingResponse(clock, day.boundary.closes_at)
    app = _service(factory, clock, crossing, summaries)
    attempt = app.history(target).attempts[0]

    with pytest.raises(TimelineDayReadOnlyError):
        list(app.stream(target, attempt.id))

    history = app.history(target)
    assert tuple(message.role for message in history.messages) == ("user",)
    assert history.attempts[-1].status == "interrupted"
    assert history.attempts[-1].incomplete_output == "Too late"
    assert DbTimelineDayRepository(factory).get(target.scope, target.entry_id).is_closed


def test_archive_race_fences_late_persona_commit(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Preserve streamed evidence but reject a commit after Timeline archival.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    summaries = FakeSummary()
    _, target = _start_day(factory, clock, FakeResponse(), summaries, "Archive me")
    gateway = ArchivingResponse(
        DbTimelineRepository(factory),
        target.scope.identity_id,
        target.scope.persona_id,
        target.scope.continuity_id,
    )
    app = _service(factory, clock, gateway, summaries)
    attempt = app.history(target).attempts[0]

    with pytest.raises(ArchivedContinuityError):
        list(app.stream(target, attempt.id))

    history = app.history(target)
    assert tuple(message.role for message in history.messages) == ("user",)
    assert history.attempts[-1].status == "failed"
    assert history.attempts[-1].incomplete_output == "Archived output"


def test_incomplete_timeline_attempt_recovers_after_service_restart(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Continue one unmatched input without admitting failed partial output.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    failing = FakeResponse()
    failing.chunks = ("Partial",)
    failing.fail = True
    summaries = FakeSummary()
    app, target = _start_day(factory, clock, failing, summaries, "Recover me")
    attempt = app.history(target).attempts[0]

    with pytest.raises(ProviderInvocationError):
        list(app.stream(target, attempt.id))

    recovered_gateway = FakeResponse()
    restarted = _service(factory, clock, recovered_gateway, summaries)
    continued = restarted.continue_incomplete_turn(target)
    list(restarted.stream(target, continued.id))
    history = restarted.history(target)
    assert history.messages[-1].content == "Hello there"
    assert history.attempts[-2].incomplete_output == "Partial"
    assert all(
        "Partial" not in message.content for message in recovered_gateway.captured[-1]
    )


def test_open_day_branching_preserves_every_saved_future(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Branch in place on the latest open day without deleting graph nodes.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    app, target = _start_day(factory, clock, responses, FakeSummary(), "First")
    list(app.stream(target, app.history(target).attempts[0].id))
    first_response_id = app.history(target).messages[-1].id
    second = app.send(target, SubmittedInput(content="Second"))
    list(app.stream(target, second.id))
    saved_leaf_id = app.history(target).messages[-1].id
    before = app.inspect_graph(target)

    selected = app.branch_from_here(target, first_response_id, saved_leaf_id)

    assert selected.selected_leaf_id == first_response_id
    assert tuple(node.message for node in app.inspect_graph(target).nodes) == tuple(
        node.message for node in before.nodes
    )
    branched = app.send(target, SubmittedInput(content="Alternate second"))
    list(app.stream(target, branched.id))
    graph = app.inspect_graph(target)
    assert saved_leaf_id in {node.message.id for node in graph.nodes}


def test_closed_day_graph_actions_return_stable_reason_and_preserve_graph(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject retry, selection, and branching after observed day closure.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    clock = MutableClock(datetime(2026, 11, 2, 8, tzinfo=UTC))
    responses = FakeResponse()
    app, target = _start_day(factory, clock, responses, FakeSummary(), "Close me")
    list(app.stream(target, app.history(target).attempts[0].id))
    original_id = app.history(target).messages[-1].id
    retry = app.retry_completed_response(target)
    list(app.stream(target, retry.id))
    selected_id = app.history(target).messages[-1].id
    before = app.inspect_graph(target)
    assert target.entry_id is not None
    day = DbTimelineDayRepository(factory).get(target.scope, target.entry_id)
    clock.value = day.boundary.closes_at

    closed_view = app.inspect_graph(target)
    assert not any(node.branchable for node in closed_view.nodes)
    actions = (
        lambda: app.retry_completed_response(target),
        lambda: app.select_alternative(target, original_id, selected_id),
        lambda: app.branch_from_here(target, original_id, selected_id),
        lambda: app.send(target, SubmittedInput(content="Too late")),
    )
    for action in actions:
        with pytest.raises(TimelineDayReadOnlyError) as error:
            action()
        assert error.value.reason == TimelineGraphActionUnavailableReason.CLOSED_DAY

    after = app.inspect_graph(target)
    assert tuple(node.message for node in after.nodes) == tuple(
        node.message for node in before.nodes
    )


def _start_day(
    factory: sessionmaker[Session],
    clock: MutableClock,
    responses: FakeResponse,
    summaries: FakeSummary,
    content: str,
) -> tuple[ConversationService, ConversationTarget]:
    """Start a Timeline and atomically reserve its first day interaction.

    Args:
        factory:
            Isolated Characters sessions.
        clock:
            Injected current instant.
        responses:
            Capturing response gateway.
        summaries:
            Capturing summary gateway.
        content:
            First user input.

    Returns:
        Conversation service and exact Timeline day target.
    """

    request = _request(factory)
    timelines = DbTimelineRepository(factory)
    started = timelines.start(
        request, resolve_starting_relationship(request.relationship)
    )
    assert started.timeline is not None
    app = _service(factory, clock, responses, summaries)
    reserved = TimelineDayService(
        timelines,
        DbTimelineDayRepository(factory),
        DbConversationRepository(factory),
        clock,
    ).reserve(
        started.timeline.identity_id,
        started.timeline.persona_id,
        started.timeline.id,
        SubmittedInput(content=content),
        _registry(responses, summaries).resolve_default("response"),
    )
    assert reserved.day is not None
    return app, ConversationTarget(
        scope=reserved.day.scope,
        mode=ContinuityMode.TIMELINE,
        entry_id=reserved.day.id,
    )


def _service(
    factory: sessionmaker[Session],
    clock: MutableClock,
    responses: FakeResponse,
    summaries: FakeSummary,
) -> ConversationService:
    """Compose Timeline conversation orchestration from real repositories.

    Args:
        factory:
            Isolated Characters sessions.
        clock:
            Injected current instant.
        responses:
            Capturing response gateway.
        summaries:
            Capturing summary gateway.

    Returns:
        Fresh conversation service suitable for restart coverage.
    """

    conversations = DbConversationRepository(factory)
    timelines = DbTimelineRepository(factory)
    return ConversationService(
        conversations,
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        _registry(responses, summaries),
        ResponseStyleService(DbResponseStyleRepository(factory)),
        timeline_adapter=TimelineConversationAdapter(
            timelines,
            DbTimelineDayRepository(factory),
            conversations,
            clock,
        ),
    )


def _registry(
    responses: FakeResponse, summaries: FakeSummary
) -> ConfiguredModelRegistry:
    """Build deterministic response and summary capabilities.

    Args:
        responses:
            Capturing response gateway.
        summaries:
            Capturing summary gateway.

    Returns:
        Bounded fake model registry.
    """

    model = ModelDescriptor(
        provider="fake",
        model="timeline",
        context_tokens=196,
        output_tokens=32,
        capabilities=frozenset({"response", "summary"}),
        parameters=frozenset(),
    )
    return ConfiguredModelRegistry(
        models=(model,),
        responses={"fake": responses},
        summaries={"fake": summaries},
        counters={"fake": MessageCountCounter()},
        defaults={"response": ("fake", "timeline"), "summary": ("fake", "timeline")},
    )
