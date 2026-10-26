"""Structural Storyline fork integration coverage."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ConversationService,
    StorylineForkService,
    StorylineService,
)
from chat_buddy.characters.domain import (
    ConversationTarget,
    EffectiveGeneration,
    IdentityDetails,
    Scene,
    Storyline,
    StorylineForkConflictError,
    SubmittedInput,
    SummaryRevision,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineForkRepository,
    DbStorylineRepository,
    DbSummaryRepository,
)
from tests.characters_support import FakeResponse
from tests.integration.characters.test_storyline_conversations import (
    _service,
    _target,
)
from tests.integration.characters.test_storyline_repositories import (
    _next_scene,
    _repositories_and_request,
)


def test_fork_copies_off_path_branch_ancestry_and_remaps_provenance(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Copy through an off-path branch point without changing source futures.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    prepared = _prepared_older_scene(factory)
    (
        storylines,
        scenes,
        lifecycle,
        source_storyline,
        _,
        source_target,
        app,
        first_response_id,
        source_leaf_id,
    ) = prepared
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    duplicate = identities.create(identities.get(source_storyline.identity_id).details)
    forks = StorylineForkService(
        storylines,
        scenes,
        DbConversationRepository(factory),
        DbConversationRepository(factory),
        identities,
        personas,
        DbStorylineForkRepository(factory),
    )

    preview = forks.preview(
        request_id=uuid4(),
        name="A gentler departure",
        target=source_target,
        branch_point_message_id=first_response_id,
        expected_selected_leaf_id=source_leaf_id,
        expected_storyline_revision=source_storyline.revision + 1,
        target_identity_id=duplicate.id,
        target_persona_id=source_storyline.persona_id,
    )
    result = forks.confirm(preview)
    repeated = forks.confirm(preview)

    assert repeated == result
    with pytest.raises(StorylineForkConflictError, match="already owns"):
        forks.preview(
            request_id=uuid4(),
            name="Occupied pair",
            target=source_target,
            branch_point_message_id=first_response_id,
            expected_selected_leaf_id=source_leaf_id,
            expected_storyline_revision=source_storyline.revision + 1,
            target_identity_id=result.storyline.identity_id,
            target_persona_id=result.storyline.persona_id,
        )
    assert result.storyline.name == "A gentler departure"
    assert result.storyline.relationship == source_storyline.relationship
    assert result.storyline.identity_id == duplicate.id
    assert result.storyline.persona_id == source_storyline.persona_id
    assert len(result.scenes) == 1
    copied_graph = DbConversationRepository(factory).graph(result.scenes[0].scope)
    assert tuple(node.content for node in copied_graph.nodes) == (
        "First question",
        "First response",
    )
    assert copied_graph.selected_leaf_id != first_response_id
    assert {mapping.kind for mapping in result.mappings} >= {
        "identity",
        "persona",
        "continuity",
        "scene",
        "conversation",
        "message",
        "attempt",
        "summary",
    }
    copied_response = copied_graph.nodes[-1]
    assert copied_response.response_provenance is not None
    attempt_mapping = next(
        mapping for mapping in result.mappings if mapping.kind == "attempt"
    )
    assert copied_response.response_provenance.attempt_id == attempt_mapping.target_id
    assert copied_response.response_provenance.attempt_id != attempt_mapping.source_id
    copied_summary = DbSummaryRepository(factory).get_current(result.scenes[0].scope)
    assert copied_summary is not None
    assert copied_summary.content == "A compatible source summary."
    assert copied_summary.checkpoint_message_id != first_response_id

    source_graph = app.inspect_graph(source_target)
    assert source_graph.selected_leaf_id == source_leaf_id
    assert tuple(node.message.content for node in source_graph.nodes) == (
        "First question",
        "First response",
        "First alternative",
        "Second question",
        "Second response",
    )
    assert identities.get(duplicate.id).is_frozen

    fork_app = _service(factory, FakeResponse(), storylines, scenes)
    fork_target = _target(result.scenes[0].id, result.scenes[0].scope)
    fork_attempt = fork_app.send(fork_target, SubmittedInput(content="New future"))
    list(fork_app.stream(fork_target, fork_attempt.id))
    source_latest = lifecycle.resume_latest(
        source_storyline.identity_id,
        source_storyline.persona_id,
        source_storyline.id,
    )[1]
    source_latest_target = _target(source_latest.id, source_latest.scope)
    source_attempt = app.send(
        source_latest_target, SubmittedInput(content="Original future")
    )
    list(app.stream(source_latest_target, source_attempt.id))
    assert fork_app.history(fork_target).messages[-1].content == "Hello there"
    assert app.history(source_latest_target).messages[-1].content == "Second response"


def test_fork_rejects_revised_duplicate_and_changed_source(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject confirmation after either reviewed profile or source revision changes.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    prepared = _prepared_older_scene(factory)
    (
        storylines,
        scenes,
        lifecycle,
        source_storyline,
        source_scene,
        source_target,
        _,
        first_response_id,
        source_leaf_id,
    ) = prepared
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    duplicate = identities.create(identities.get(source_storyline.identity_id).details)
    forks = StorylineForkService(
        storylines,
        scenes,
        DbConversationRepository(factory),
        DbConversationRepository(factory),
        identities,
        personas,
        DbStorylineForkRepository(factory),
    )
    preview = forks.preview(
        request_id=uuid4(),
        name="Reviewed fork",
        target=source_target,
        branch_point_message_id=first_response_id,
        expected_selected_leaf_id=source_leaf_id,
        expected_storyline_revision=source_storyline.revision + 1,
        target_identity_id=duplicate.id,
        target_persona_id=source_storyline.persona_id,
    )
    with pytest.raises(StorylineForkConflictError, match="persona branch point"):
        forks.preview(
            request_id=uuid4(),
            name="Invalid branch point",
            target=source_target,
            branch_point_message_id=uuid4(),
            expected_selected_leaf_id=source_leaf_id,
            expected_storyline_revision=source_storyline.revision + 1,
            target_identity_id=duplicate.id,
            target_persona_id=source_storyline.persona_id,
        )

    identities.replace(
        duplicate.id,
        IdentityDetails(name="Changed after review"),
        duplicate.revision,
    )
    with pytest.raises(StorylineForkConflictError, match="identity changed"):
        forks.confirm(preview)

    second_duplicate = identities.create(
        identities.get(source_storyline.identity_id).details
    )
    second_preview = forks.preview(
        request_id=uuid4(),
        name="Stale source",
        target=source_target,
        branch_point_message_id=first_response_id,
        expected_selected_leaf_id=source_leaf_id,
        expected_storyline_revision=source_storyline.revision + 1,
        target_identity_id=second_duplicate.id,
        target_persona_id=source_storyline.persona_id,
    )
    lifecycle.rename_scene(
        source_scene.scope,
        source_scene.id,
        "Changed source title",
        source_storyline.revision + 1,
    )
    with pytest.raises(StorylineForkConflictError, match="Source Storyline changed"):
        forks.confirm(second_preview)


def _prepared_older_scene(
    factory: sessionmaker[Session],
) -> tuple[
    DbStorylineRepository,
    DbSceneRepository,
    StorylineService,
    Storyline,
    Scene,
    ConversationTarget,
    ConversationService,
    UUID,
    UUID,
]:
    """Create a two-turn source scene followed by one empty dependent scene.

    Args:
        factory:
            Isolated Characters database factory.

    Returns:
        Repositories, services, source ownership, and guarded message identifiers.
    """

    storylines, scenes, request = _repositories_and_request(factory)
    lifecycle = StorylineService(storylines, scenes, DbConversationRepository(factory))
    storyline, scene = lifecycle.start(request)
    target = _target(scene.id, scene.scope)
    responses = FakeResponse()
    app = _service(factory, responses, storylines, scenes)
    responses.chunks = ("First response",)
    first = app.send(target, SubmittedInput(content="First question"))
    list(app.stream(target, first.id))
    first_response_id = app.history(target).messages[-1].id
    source_graph = app.inspect_graph(target)
    first_response = next(
        node.message
        for node in source_graph.nodes
        if node.message.id == first_response_id
    )
    assert first_response.response_provenance is not None
    response_generation = first_response.response_provenance.generation
    summary_generation = EffectiveGeneration.model_validate(
        response_generation.model_copy(
            update={
                "model": response_generation.model.model_copy(
                    update={"capabilities": frozenset({"response", "summary"})}
                ),
                "capability": "summary",
            }
        ).model_dump()
    )
    DbSummaryRepository(factory).append(
        SummaryRevision(
            id=uuid4(),
            scope=scene.scope,
            revision=1,
            predecessor_id=None,
            checkpoint_message_id=first_response_id,
            checkpoint_sequence=2,
            content="A compatible source summary.",
            generation=summary_generation,
            created_at=datetime.now(UTC),
        ),
        expected_revision=None,
        expected_checkpoint_id=None,
    )
    responses.chunks = ("First alternative",)
    retry = app.retry_completed_response(target)
    list(app.stream(target, retry.id))
    responses.chunks = ("Second response",)
    second = app.send(target, SubmittedInput(content="Second question"))
    list(app.stream(target, second.id))
    source_leaf_id = app.history(target).messages[-1].id
    eligibility = lifecycle.append_eligibility(
        storyline.identity_id, storyline.persona_id, storyline.id
    )
    lifecycle.append_next(_next_scene(), eligibility)
    return (
        storylines,
        scenes,
        lifecycle,
        storyline,
        scene,
        target,
        app,
        first_response_id,
        source_leaf_id,
    )
