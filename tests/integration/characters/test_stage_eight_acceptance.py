"""End-to-end acceptance of Stage 8 Timeline and response-style behavior."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ResponseStyleService,
    TimelineDayService,
    TimelineService,
)
from chat_buddy.characters.domain import (
    NarrativePlacement,
    PersonaCore,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateStatus,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbResponseStyleRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)
from tests.characters_support import FakeResponse
from tests.evaluations.test_characters_evolution_harness import (
    test_timeline_native_scenarios_preserve_conservative_and_selected_evidence as _prove_evaluation_gates,
)
from tests.integration.characters.test_timeline_conversations import (
    FakeSummary,
    MutableClock,
    _start_day,
)
from tests.integration.characters.test_timeline_conversations import (
    test_closed_day_graph_actions_return_stable_reason_and_preserve_graph as _prove_closed_day_guards,
)
from tests.integration.characters.test_timeline_day_service import (
    test_first_send_reuses_today_and_offline_gap_creates_one_next_day as _prove_offline_gap,
)
from tests.integration.characters.test_timeline_evolution import (
    test_timeline_day_boundaries_replay_corrections_and_future_exclusion as _prove_temporal_evolution,
)
from tests.integration.characters.test_timeline_evolution import (
    test_timeline_open_day_alternative_rebuilds_and_rejects_unselected_evidence as _prove_alternative_rebuild,
)
from tests.integration.characters.test_timeline_evolution import (
    test_timeline_snapshot_admits_prior_memory_only_with_exact_selected_sources as _prove_temporal_memory,
)
from tests.integration.characters.test_timeline_lifecycle import (
    MutableTimezoneSource,
    _review,
)
from tests.integration.characters.test_timeline_lifecycle import (
    test_timeline_service_starts_resumes_and_archives_without_creating_days as _prove_lifecycle,
)
from tests.integration.characters.test_timeline_repositories import _generation


def test_stage_eight_milestone(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Prove the complete deterministic Stage 8 milestone.

    Args:
        characters_session_factory:
            Isolated Characters database sessions.
    """

    prove_stage_eight_milestone(characters_session_factory)


def prove_stage_eight_milestone(factory: sessionmaker[Session]) -> None:
    """Exercise Timeline calendar, style, derivation, and lifecycle guarantees.

    The chapters share one persistence factory and use only injected clocks and
    fake providers. Together they cover the complete user journey while keeping
    each failure localized to the focused workflow that owns the behavior.

    Args:
        factory:
            SQLite or disposable PostgreSQL Characters sessions.
    """

    _prove_lifecycle(factory)
    _prove_timeline_style_attempt_boundaries(factory)
    _prove_offline_gap(factory)
    _prove_captured_zone_across_dst_and_host_zone_change(factory)
    _prove_temporal_evolution(factory)
    _prove_temporal_memory(factory)
    _prove_alternative_rebuild(factory)
    _prove_closed_day_guards(factory)
    _prove_evaluation_gates()


def _prove_timeline_style_attempt_boundaries(
    factory: sessionmaker[Session],
) -> None:
    """Keep historical styles while sends and retries use the latest revision.

    Args:
        factory:
            Characters database sessions shared by the acceptance journey.
    """

    clock = MutableClock(datetime(2026, 6, 15, 12, tzinfo=UTC))
    gateway = FakeResponse()
    app, target = _start_day(
        factory,
        clock,
        gateway,
        FakeSummary(),
        "Begin with the original style.",
    )
    first_attempt = app.history(target).attempts[0]
    assert first_attempt.response_style.source_revision == 1
    list(app.stream(target, first_attempt.id))
    first_response = app.history(target).messages[-1]

    styles = ResponseStyleService(DbResponseStyleRepository(factory))
    second_style = styles.update(
        target.scope.continuity_id,
        ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.LIGHT,
            response_length=ResponseLength.CONCISE,
            narrative_placement=NarrativePlacement.BEFORE_DIALOGUE,
        ),
        expected_revision=1,
    )
    assert second_style.status == StyleUpdateStatus.UPDATED
    gateway.chunks = ("Concise next response",)
    second_attempt = app.send(
        target, SubmittedInput(content="Use the newly saved style.")
    )
    assert second_attempt.response_style.source_revision == 2
    list(app.stream(target, second_attempt.id))
    second_response = app.history(target).messages[-1]

    third_style = styles.update(
        target.scope.continuity_id,
        ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.RICH,
            response_length=ResponseLength.EXPANSIVE,
            narrative_placement=NarrativePlacement.AFTER_DIALOGUE,
        ),
        expected_revision=2,
    )
    assert third_style.status == StyleUpdateStatus.UPDATED
    gateway.chunks = ("Expanded retry response",)
    retry = app.retry_completed_response(target)
    assert retry.response_style.source_revision == 3
    list(app.stream(target, retry.id))
    retry_response = app.history(target).messages[-1]

    graph = app.inspect_graph(target)
    snapshots = {
        node.message.id: node.message.response_provenance.response_style
        for node in graph.nodes
        if node.message.response_provenance is not None
    }
    assert snapshots[first_response.id].source_revision == 1
    assert snapshots[second_response.id].source_revision == 2
    assert snapshots[retry_response.id].source_revision == 3
    assert second_response.content == "Concise next response"
    assert retry_response.content == "Expanded retry response"
    assert {node.message.id for node in graph.nodes} >= {
        first_response.id,
        second_response.id,
        retry_response.id,
    }


def _prove_captured_zone_across_dst_and_host_zone_change(
    factory: sessionmaker[Session],
) -> None:
    """Keep one captured zone and immutable boundaries across both DST shapes.

    Args:
        factory:
            Characters database sessions shared by the acceptance journey.
    """

    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    identity = identities.ensure_default()
    persona = personas.create(
        PersonaCore(name="Calendar Friend", definition="Notices changing seasons")
    )
    source = MutableTimezoneSource("America/New_York")
    timelines = TimelineService(
        DbTimelineRepository(factory),
        DbTimelineDayRepository(factory),
        source,
    )
    started = timelines.start(
        _review(identity.id, identity.revision, persona.id, persona.revision)
    )
    assert started.timeline is not None
    timeline = started.timeline
    assert timeline.calendar_timezone.name == "America/New_York"

    clock = MutableClock(datetime(2026, 3, 8, 12, tzinfo=UTC))
    days = TimelineDayService(
        DbTimelineRepository(factory),
        DbTimelineDayRepository(factory),
        DbConversationRepository(factory),
        clock,
    )
    spring = days.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="The clocks moved forward."),
        _generation(),
    )
    assert spring.day is not None
    spring_boundary = spring.day.boundary
    assert spring_boundary.opens_at == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert spring_boundary.closes_at == datetime(2026, 3, 9, 4, tzinfo=UTC)

    source.name = "Asia/Tehran"
    clock.value = datetime(2026, 11, 1, 12, tzinfo=UTC)
    fall = days.reserve(
        timeline.identity_id,
        timeline.persona_id,
        timeline.id,
        SubmittedInput(content="The clocks moved back."),
        _generation(),
    )
    assert fall.day is not None
    assert fall.day.boundary.opens_at == datetime(2026, 11, 1, 4, tzinfo=UTC)
    assert fall.day.boundary.closes_at == datetime(2026, 11, 2, 5, tzinfo=UTC)

    resumed = timelines.resume(timeline.identity_id, timeline.persona_id, timeline.id)
    assert resumed.timeline.calendar_timezone.name == "America/New_York"
    assert source.calls == 1
    assert tuple(day.position for day in resumed.days) == (1, 2)
    assert resumed.days[0].boundary == spring_boundary
