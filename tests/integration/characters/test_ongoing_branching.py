"""Ongoing branch actions and exact saved-future selection."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    ConversationNotFoundError,
    InvalidParentError,
    StaleSelectionError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
)
from tests.characters_support import FakeResponse, service, start


def test_branch_and_exact_future_selection_preserve_every_saved_node(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep divergent futures immutable and restorable after a new branch.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    first = app.send(scope, SubmittedInput(content="First"))
    list(app.stream(scope, first.id))
    branch_point_id = app.history(scope).messages[-1].id
    second = app.send(scope, SubmittedInput(content="Old future"))
    list(app.stream(scope, second.id))
    old_leaf_id = app.history(scope).messages[-1].id
    original = app.inspect_graph(scope)

    branched = app.branch_from_here(scope, branch_point_id, old_leaf_id)
    assert branched.selected_leaf_id == branch_point_id
    gateway.chunks = ("New answer",)
    replacement = app.send(scope, SubmittedInput(content="New future"))
    list(app.stream(scope, replacement.id))
    new_leaf_id = app.history(scope).messages[-1].id

    graph = app.inspect_graph(scope)
    assert graph.selected_leaf_id == new_leaf_id
    assert len(graph.nodes) == 6
    branch_point = next(
        node for node in graph.nodes if node.message.id == branch_point_id
    )
    assert branch_point.selected
    assert branch_point.branchable
    assert (
        next(node for node in graph.nodes if node.message.id == old_leaf_id).selected
        is False
    )

    restored = app.select_saved_future(scope, old_leaf_id, new_leaf_id)
    assert [node.content for node in restored.messages] == [
        "First",
        "Hello there",
        "Old future",
        "Hello there",
    ]
    final = app.inspect_graph(scope)
    assert tuple(node.message for node in final.nodes[:4]) == tuple(
        node.message for node in original.nodes
    )
    assert {node.message.id for node in final.nodes} == {
        node.message.id for node in graph.nodes
    }


def test_graph_view_exposes_alternatives_retries_and_selected_state(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Derive action metadata from immutable graph structure and live state.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    initial = app.send(scope, SubmittedInput(content="Question"))
    list(app.stream(scope, initial.id))
    original_id = app.history(scope).messages[-1].id
    gateway.chunks = ("Alternative",)
    retry = app.retry_completed_response(scope)
    list(app.stream(scope, retry.id))
    selected_id = app.history(scope).messages[-1].id

    graph = app.inspect_graph(scope)
    responses = tuple(node for node in graph.nodes if node.message.role == "persona")
    assert all(node.alternative_ids == (original_id, selected_id) for node in responses)
    assert all(node.retry_count == 1 for node in responses)
    assert next(
        node for node in responses if node.message.id == selected_id
    ).selected_leaf
    assert not next(
        node for node in responses if node.message.id == original_id
    ).selected

    selected = app.select_alternative(scope, original_id, selected_id)
    assert selected.selected_leaf_id == original_id
    assert app.history(scope).messages[-1].id == original_id


def test_actions_reject_invalid_targets_stale_state_and_active_attempts(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject every unsafe graph action without changing the selected future.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    initial = app.send(scope, SubmittedInput(content="Question"))
    list(app.stream(scope, initial.id))
    original_id = app.history(scope).messages[-1].id
    gateway.chunks = ("Alternative",)
    retry = app.retry_completed_response(scope)
    list(app.stream(scope, retry.id))
    alternative_id = app.history(scope).messages[-1].id
    next_turn = app.send(scope, SubmittedInput(content="Continue"))

    with pytest.raises(AttemptConflictError):
        app.select_alternative(scope, original_id, next_turn.user_message_id)
    with pytest.raises(AttemptConflictError):
        app.branch_from_here(scope, alternative_id, next_turn.user_message_id)
    list(app.stream(scope, next_turn.id))
    leaf_id = app.history(scope).messages[-1].id

    with pytest.raises(StaleSelectionError):
        app.branch_from_here(scope, alternative_id, uuid4())
    with pytest.raises(InvalidParentError):
        app.branch_from_here(scope, original_id, leaf_id)
    with pytest.raises(InvalidParentError):
        app.branch_from_here(scope, leaf_id, leaf_id)
    with pytest.raises(InvalidParentError):
        app.select_saved_future(scope, alternative_id, leaf_id)
    with pytest.raises(InvalidParentError):
        app.select_saved_future(scope, uuid4(), leaf_id)

    forged = scope.model_copy(update={"identity_id": uuid4()})
    with pytest.raises(ConversationNotFoundError):
        app.branch_from_here(forged, alternative_id, leaf_id)


def test_archived_conversation_rejects_selection_and_branching(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep every graph mutation unavailable after archival.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    initial = app.send(scope, SubmittedInput(content="Question"))
    list(app.stream(scope, initial.id))
    original_id = app.history(scope).messages[-1].id
    gateway.chunks = ("Alternative",)
    retry = app.retry_completed_response(scope)
    list(app.stream(scope, retry.id))
    selected_id = app.history(scope).messages[-1].id
    DbContinuityRepository(characters_session_factory).archive(
        scope.identity_id, scope.persona_id, scope.continuity_id
    )

    graph = app.inspect_graph(scope)
    assert not any(node.branchable for node in graph.nodes)
    with pytest.raises(ArchivedContinuityError):
        app.select_alternative(scope, original_id, selected_id)
    with pytest.raises(ArchivedContinuityError):
        app.branch_from_here(scope, selected_id, selected_id)
