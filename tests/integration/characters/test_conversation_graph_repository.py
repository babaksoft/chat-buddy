"""Selected-path, graph-inspection, provenance, and guarded-write persistence."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ConversationNotFoundError,
    StaleSelectionError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbConversationRepository,
)
from tests.characters_support import FakeResponse, service, start


def test_completed_turn_persists_parent_graph_selection_and_provenance(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist immutable nodes while keeping ordinary history selected and linear.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hello"))
    list(app.stream(scope, attempt.id))
    repository = DbConversationRepository(characters_session_factory)

    graph = repository.graph(scope)
    path = repository.selected_path(scope)
    assert graph.selected_leaf_id == path.selected_leaf_id == graph.nodes[-1].id
    assert graph.nodes[0].parent_id is None
    assert graph.nodes[1].parent_id == graph.nodes[0].id
    assert path.messages == graph.nodes
    provenance = graph.nodes[1].response_provenance
    assert provenance is not None
    assert provenance.attempt_id == attempt.id
    assert provenance.generation == attempt.generation
    assert provenance.response_style.name == "ongoing.default"
    assert provenance.evolution_strategy.name == "baseline.no_change"
    assert [message.sequence for message in app.history(scope).messages] == [1, 2]


def test_exact_selection_preserves_old_future_and_next_send_branches(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Select an older persona node and append without deleting its old future.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    first = app.send(scope, SubmittedInput(content="First"))
    list(app.stream(scope, first.id))
    first_persona_id = app.history(scope).messages[-1].id
    second = app.send(scope, SubmittedInput(content="Old future"))
    list(app.stream(scope, second.id))
    repository = DbConversationRepository(characters_session_factory)
    old_leaf_id = repository.selected_path(scope).selected_leaf_id

    selected = repository.select_leaf(scope, first_persona_id, old_leaf_id)
    assert [node.content for node in selected.messages] == ["First", "Hello there"]
    branch = app.send(scope, SubmittedInput(content="New future"))
    list(app.stream(scope, branch.id))

    assert [message.content for message in app.history(scope).messages] == [
        "First",
        "Hello there",
        "New future",
        "Hello there",
    ]
    graph = repository.graph(scope)
    assert len(graph.nodes) == 6
    assert {node.content for node in graph.nodes} >= {"Old future", "New future"}
    assert old_leaf_id in {node.id for node in graph.nodes}


def test_selection_is_guarded_and_every_graph_read_requires_full_ownership(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject stale selection and every forged ownership component.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hello"))
    list(app.stream(scope, attempt.id))
    repository = DbConversationRepository(characters_session_factory)
    selected = repository.selected_path(scope)
    assert selected.selected_leaf_id is not None

    with pytest.raises(StaleSelectionError):
        repository.select_leaf(scope, selected.selected_leaf_id, uuid4())
    forged = scope.model_copy(update={"identity_id": uuid4()})
    with pytest.raises(ConversationNotFoundError):
        repository.selected_path(forged)
    with pytest.raises(ConversationNotFoundError):
        repository.graph(forged)


def test_alternatives_are_read_as_parent_siblings(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Resolve persona alternatives through their shared user parent.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    scope = start(characters_session_factory)
    gateway = FakeResponse()
    app = service(characters_session_factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hello"))
    list(app.stream(scope, attempt.id))
    repository = DbConversationRepository(characters_session_factory)
    path = repository.selected_path(scope)

    alternatives = repository.alternatives(scope, path.messages[0].id)
    assert alternatives.user_message_id == path.messages[0].id
    assert alternatives.responses == (path.messages[1],)
