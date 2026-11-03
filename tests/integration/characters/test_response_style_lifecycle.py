"""Response-style attempt-boundary and historical provenance coverage."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ResponseStyleService
from chat_buddy.characters.domain import (
    NarrativePlacement,
    ProviderInvocationError,
    ResponseLength,
    ResponseStyleSettings,
    SceneDescriptionLevel,
    StyleUpdateStatus,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbResponseStyleRepository,
)
from tests.characters_support import FakeResponse, ongoing_target, service, start


def test_style_snapshot_follows_attempt_boundaries_and_survives_restart(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep in-flight and historical styles while new attempts use saved changes.

    Args:
        characters_session_factory:
            Isolated Characters persistence.
    """

    factory = characters_session_factory
    scope = start(factory)
    target = ongoing_target(scope)
    gateway = FakeResponse()
    styles = ResponseStyleService(DbResponseStyleRepository(factory))
    app = service(factory, gateway)

    revision_two = styles.update(
        scope.continuity_id,
        ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.LIGHT,
            response_length=ResponseLength.CONCISE,
            narrative_placement=NarrativePlacement.BEFORE_DIALOGUE,
        ),
        expected_revision=1,
    )
    assert revision_two.status == StyleUpdateStatus.UPDATED
    first = app.send(target, SubmittedInput(content="Begin."))
    assert first.response_style.source_revision == 2

    revision_three = styles.update(
        scope.continuity_id,
        ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.RICH,
            response_length=ResponseLength.EXPANSIVE,
            narrative_placement=NarrativePlacement.AFTER_DIALOGUE,
        ),
        expected_revision=2,
    )
    assert revision_three.status == StyleUpdateStatus.UPDATED
    list(app.stream(target, first.id))
    assert first.response_style.instruction in "\n".join(
        message.content for message in gateway.captured[-1]
    )
    original = app.history(target).messages[-1]
    original_node = next(
        node.message
        for node in app.inspect_graph(target).nodes
        if node.message.id == original.id
    )
    assert original_node.response_provenance is not None
    assert original_node.response_provenance.response_style == first.response_style

    retried = app.retry_completed_response(target)
    assert retried.response_style.source_revision == 3
    gateway.chunks = ("Alternative",)
    list(app.stream(target, retried.id))
    alternative = app.history(target).messages[-1]
    graph = app.inspect_graph(target)
    alternative_node = next(
        node.message for node in graph.nodes if node.message.id == alternative.id
    )
    assert alternative_node.response_provenance is not None
    assert alternative_node.response_provenance.response_style == retried.response_style
    assert original_node.response_provenance.response_style.source_revision == 2

    gateway.chunks, gateway.fail = ("Partial",), True
    failed = app.send(target, SubmittedInput(content="Continue."))
    with pytest.raises(ProviderInvocationError):
        list(app.stream(target, failed.id))
    revision_four = styles.update(
        scope.continuity_id,
        ResponseStyleSettings(
            scene_description=SceneDescriptionLevel.NONE,
            response_length=ResponseLength.BALANCED,
            narrative_placement=NarrativePlacement.INTERLEAVED,
        ),
        expected_revision=3,
    )
    assert revision_four.status == StyleUpdateStatus.UPDATED

    gateway.chunks, gateway.fail = ("Recovered",), False
    restarted = service(factory, gateway)
    continued = restarted.continue_incomplete_turn(target)
    assert failed.response_style.source_revision == 3
    assert continued.response_style.source_revision == 4
    list(restarted.stream(target, continued.id))
    completed = restarted.history(target).messages[-1]
    completed_node = next(
        node.message
        for node in restarted.inspect_graph(target).nodes
        if node.message.id == completed.id
    )
    assert completed_node.response_provenance is not None
    assert completed_node.response_provenance.response_style == continued.response_style
