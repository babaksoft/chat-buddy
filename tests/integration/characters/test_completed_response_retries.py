"""Bounded completed-response retries and durable alternative selection."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    ConversationNotFoundError,
    ConversationSettings,
    GenerationConfiguration,
    IncompleteTurnError,
    ProviderInvocationError,
    RetryLimitError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
)
from tests.characters_support import FakeResponse, service, start


def test_three_retries_create_selected_siblings_with_current_settings(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist four alternatives and reject a fifth response reservation.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    initial = app.send(scope, SubmittedInput(content="Question"))
    list(app.stream(scope, initial.id))
    repository = DbConversationRepository(factory)
    original_leaf_id = repository.selected_path(scope).selected_leaf_id
    assert original_leaf_id is not None
    settings = ConversationSettings(
        provider="fake",
        model="second",
        requested=GenerationConfiguration(temperature=0.4),
    )
    app.configure(scope, settings)
    selected_leaf_id = original_leaf_id

    for number in range(1, 4):
        availability = app.retry_availability(scope)
        assert availability.successful_response_count == number
        assert availability.retries_remaining == 4 - number
        gateway.chunks = (f"Alternative {number}",)
        attempt = app.retry_completed_response(scope)
        assert repository.selected_path(scope).selected_leaf_id == selected_leaf_id
        assert attempt.generation.model.model == "second"
        assert attempt.generation.configuration.temperature == 0.4
        assert list(app.stream(scope, attempt.id)) == [f"Alternative {number}"]
        next_selected_leaf_id = repository.selected_path(scope).selected_leaf_id
        assert next_selected_leaf_id is not None
        selected_leaf_id = next_selected_leaf_id

    availability = app.retry_availability(scope)
    assert availability.successful_response_count == 4
    assert availability.retries_remaining == 0
    with pytest.raises(RetryLimitError):
        app.retry_completed_response(scope)

    graph = repository.graph(scope)
    alternatives = repository.alternatives(scope, availability.user_message_id)
    assert len(alternatives.responses) == 4
    assert graph.selected_leaf_id == alternatives.responses[-1].id
    assert {node.parent_id for node in alternatives.responses} == {
        availability.user_message_id
    }
    assert all(node.response_provenance is not None for node in alternatives.responses)
    assert alternatives.responses[-1].response_provenance is not None
    assert alternatives.responses[-1].response_provenance.generation.model.model == (
        "second"
    )
    retry_prompt = gateway.captured[-1]
    assert any(message.content == "Question" for message in retry_prompt)
    assert all(message.content != "Alternative 2" for message in retry_prompt)


def test_failed_and_interrupted_retries_preserve_selection_and_allowance(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Count only committed persona siblings toward the retry limit.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    initial = app.send(scope, SubmittedInput(content="Question"))
    list(app.stream(scope, initial.id))
    repository = DbConversationRepository(factory)
    selected = repository.selected_path(scope).selected_leaf_id

    gateway.chunks, gateway.fail = ("Partial",), True
    failed = app.retry_completed_response(scope)
    with pytest.raises(ProviderInvocationError):
        list(app.stream(scope, failed.id))
    assert repository.selected_path(scope).selected_leaf_id == selected
    assert app.retry_availability(scope).retries_remaining == 3

    gateway.chunks, gateway.fail = ("Interrupted", " ignored"), False
    interrupted = app.retry_completed_response(scope)
    stream = app.stream(scope, interrupted.id)
    assert next(stream) == "Interrupted"
    stream.close()
    assert repository.selected_path(scope).selected_leaf_id == selected
    assert app.retry_availability(scope).retries_remaining == 3

    gateway.chunks = ("Committed",)
    completed = app.retry_completed_response(scope)
    list(app.stream(scope, completed.id))
    saved = app.history(scope)
    assert [attempt.status for attempt in saved.attempts] == [
        "completed",
        "failed",
        "interrupted",
        "completed",
    ]
    assert app.retry_availability(scope).retries_remaining == 2


def test_retry_rejects_missing_foreign_stale_and_archived_targets(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Fence invalid retry states without changing committed history.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    with pytest.raises(IncompleteTurnError):
        app.retry_completed_response(scope)
    initial = app.send(scope, SubmittedInput(content="Question"))
    with pytest.raises(AttemptConflictError):
        app.retry_completed_response(scope)
    list(app.stream(scope, initial.id))
    original_response_id = app.history(scope).messages[-1].id

    forged = scope.model_copy(update={"identity_id": uuid4()})
    with pytest.raises(ConversationNotFoundError):
        app.retry_completed_response(forged)

    gateway.chunks = ("First alternative",)
    first_retry = app.retry_completed_response(scope)
    list(app.stream(scope, first_retry.id))
    retry = app.retry_completed_response(scope)
    repository = DbConversationRepository(factory)
    repository.claim(scope, retry.id)
    repository.append(scope, retry.id, "Late alternative")
    selected = repository.selected_path(scope).selected_leaf_id
    assert selected is not None
    repository.select_leaf(scope, original_response_id, selected)
    with pytest.raises(AttemptConflictError):
        repository.complete(scope, retry.id)
    repository.stop(scope, retry.id, "failed")

    DbContinuityRepository(factory).archive(
        scope.identity_id, scope.persona_id, scope.continuity_id
    )
    with pytest.raises(ArchivedContinuityError):
        app.retry_completed_response(scope)
    assert all(
        message.content != "Late alternative" for message in app.history(scope).messages
    )
