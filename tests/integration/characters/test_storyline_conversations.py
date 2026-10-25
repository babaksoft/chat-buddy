"""Storyline scene conversation and summary integration coverage."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ConversationService,
    StorylineConversationAdapter,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ContinuityMode,
    ConversationScope,
    ConversationTarget,
    ForkRequiredError,
    InvalidSceneOwnershipError,
    ModelDescriptor,
    ProviderInvocationError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import ConfiguredModelRegistry
from tests.characters_support import FakeResponse, registry
from tests.integration.characters.test_ongoing_summary_context import (
    FakeSummary,
    MessageCountCounter,
)
from tests.integration.characters.test_storyline_repositories import (
    _next_scene,
    _repositories_and_request,
)


def test_storyline_scene_supports_recovery_retries_selection_and_restart(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Exercise the complete graph lifecycle through one mode-owned target.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    gateway = FakeResponse()
    storylines, scenes, request = _repositories_and_request(factory)
    storyline, scene = StorylineService(
        storylines, scenes, DbConversationRepository(factory)
    ).start(request)
    target = _target(scene.id, scene.scope)
    app = _service(factory, gateway, storylines, scenes)

    first = app.send(target, SubmittedInput(content="Are we leaving?"))
    assert scenes.get(scene.scope, scene.id).setup_locked
    gateway.chunks = ("Not yet.",)
    assert list(app.stream(target, first.id)) == ["Not yet."]
    original = app.history(target).messages[-1]

    gateway.chunks = ("Soon.",)
    retry = app.retry_completed_response(target)
    list(app.stream(target, retry.id))
    alternative = app.history(target).messages[-1]
    assert alternative.id != original.id
    selected = app.select_alternative(target, original.id, alternative.id)
    assert selected.selected_leaf_id == original.id

    gateway.chunks, gateway.fail = ("Partial",), True
    failed = app.send(target, SubmittedInput(content="What happened?"))
    with pytest.raises(ProviderInvocationError, match="Provider failed"):
        list(app.stream(target, failed.id))
    gateway.chunks, gateway.fail = ("Recovered.",), False
    restarted = _service(factory, gateway, storylines, scenes)
    continued = restarted.continue_incomplete_turn(target)
    assert continued.user_message_id == failed.user_message_id
    assert list(restarted.stream(target, continued.id)) == ["Recovered."]
    assert all("Partial" not in message.content for message in gateway.captured[-1])

    graph = restarted.inspect_graph(target)
    provenance = next(
        node.message.response_provenance
        for node in graph.nodes
        if node.message.id == original.id
    )
    assert provenance is not None
    assert provenance.response_style == request.initial_scene.response_style
    assert storyline.id == target.scope.continuity_id


def test_storyline_summaries_and_short_term_context_stay_inside_the_scene(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Compress one scene and exclude its summary and transcript from the next.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    responses = FakeResponse()
    summaries = FakeSummary()
    storylines, scenes, request = _repositories_and_request(factory)
    lifecycle = StorylineService(storylines, scenes, DbConversationRepository(factory))
    storyline, first_scene = lifecycle.start(request)
    first_target = _target(first_scene.id, first_scene.scope)
    app = _summary_service(factory, responses, summaries, storylines, scenes)

    for text in ("First-scene one", "First-scene two"):
        attempt = app.send(first_target, SubmittedInput(content=text))
        list(app.stream(first_target, attempt.id))
    third = app.send(first_target, SubmittedInput(content="First-scene three"))
    list(app.stream(first_target, third.id))
    assert DbSummaryRepository(factory).get_current(first_scene.scope) is not None

    eligibility = lifecycle.append_eligibility(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    sequence = lifecycle.append_next(_next_scene(), eligibility)
    second_scene = sequence.scenes[-1]
    second_target = _target(second_scene.id, second_scene.scope)
    responses.captured.clear()
    attempt = app.send(second_target, SubmittedInput(content="Second-scene only"))
    list(app.stream(second_target, attempt.id))

    prompt_text = "\n".join(message.content for message in responses.captured[-1])
    assert "Second-scene only" in prompt_text
    assert "The train leaves at midnight." in prompt_text
    assert "First-scene" not in prompt_text
    assert "Durable summary" not in prompt_text
    assert DbSummaryRepository(factory).get_current(second_scene.scope) is None

    with pytest.raises(ForkRequiredError):
        app.send(first_target, SubmittedInput(content="Rewrite the past"))


def test_storyline_conversation_rejects_archive_and_foreign_scene_ownership(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject archived writes and mismatched scene identifiers before reservation.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    gateway = FakeResponse()
    storylines, scenes, request = _repositories_and_request(factory)
    lifecycle = StorylineService(storylines, scenes, DbConversationRepository(factory))
    storyline, scene = lifecycle.start(request)
    target = _target(scene.id, scene.scope)
    app = _service(factory, gateway, storylines, scenes)
    attempt = app.send(target, SubmittedInput(content="One turn"))
    list(app.stream(target, attempt.id))

    archived = lifecycle.archive(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        storyline.revision,
    )
    with pytest.raises(ArchivedContinuityError):
        app.send(target, SubmittedInput(content="Too late"))
    assert app.history(target).messages[-1].role == "persona"
    assert archived.lifecycle == "archived"

    foreign = target.model_copy(update={"scene_id": uuid4()})
    with pytest.raises(InvalidSceneOwnershipError):
        app.history(foreign)


def _target(scene_id: UUID, scope: ConversationScope) -> ConversationTarget:
    """Build an explicit Storyline target from persisted scene ownership.

    Args:
        scene_id:
            Persisted scene identifier.
        scope:
            Persisted complete conversation ownership.

    Returns:
        Validated Storyline conversation target.
    """

    return ConversationTarget(
        scope=scope, mode=ContinuityMode.STORYLINE, scene_id=scene_id
    )


def _service(
    factory: sessionmaker[Session],
    responses: FakeResponse,
    storylines: DbStorylineRepository,
    scenes: DbSceneRepository,
) -> ConversationService:
    """Compose Storyline conversation orchestration with real repositories.

    Args:
        factory:
            Isolated Characters database factory.
        responses:
            Capturing response provider.
        storylines:
            Storyline ownership repository.
        scenes:
            Scene ownership repository.

    Returns:
        Fresh Storyline-aware conversation service.
    """

    return ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        registry(responses),
        storyline_adapter=StorylineConversationAdapter(storylines, scenes),
    )


def _summary_service(
    factory: sessionmaker[Session],
    responses: FakeResponse,
    summaries: FakeSummary,
    storylines: DbStorylineRepository,
    scenes: DbSceneRepository,
) -> ConversationService:
    """Compose a small-budget Storyline service with summary capability.

    Args:
        factory:
            Isolated Characters database factory.
        responses:
            Capturing response provider.
        summaries:
            Capturing summary provider.
        storylines:
            Storyline ownership repository.
        scenes:
            Scene ownership repository.

    Returns:
        Fresh bounded Storyline conversation service.
    """

    models = (
        ModelDescriptor(
            provider="fake",
            model="response",
            context_tokens=170,
            output_tokens=10,
            capabilities=frozenset({"response"}),
        ),
        ModelDescriptor(
            provider="fake",
            model="summary",
            context_tokens=170,
            output_tokens=10,
            capabilities=frozenset({"summary"}),
        ),
    )
    models_registry = ConfiguredModelRegistry(
        models=models,
        responses={"fake": responses},
        summaries={"fake": summaries},
        counters={"fake": MessageCountCounter()},
        defaults={
            "response": ("fake", "response"),
            "summary": ("fake", "summary"),
        },
    )
    return ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        models_registry,
        storyline_adapter=StorylineConversationAdapter(storylines, scenes),
    )
