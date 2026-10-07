"""End-to-end acceptance of Stage 5 retry and branching behavior."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    ConversationNotFoundError,
    ProviderInvocationError,
    RetryLimitError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbSummaryRepository,
)
from tests.characters_support import FakeResponse, start
from tests.integration.characters.test_ongoing_summary_context import (
    FakeSummary,
    _service,
)


def test_stage_five_milestone(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Prove selected-path isolation, recovery, and ownership end to end.

    Args:
        characters_session_factory:
            Isolated Characters database sessions.
    """

    prove_stage_five_milestone(characters_session_factory)


def prove_stage_five_milestone(factory: sessionmaker[Session]) -> None:
    """Exercise the complete retry and branching milestone.

    Args:
        factory:
            SQLite or disposable PostgreSQL Characters sessions.
    """

    scope = start(factory)
    responses = FakeResponse()
    summaries = FakeSummary()
    app = _service(factory, responses, summaries)
    summary_repository = DbSummaryRepository(factory)

    for content in ("First", "Second", "Third", "Fourth"):
        attempt = app.send(scope, SubmittedInput(content=content))
        list(app.stream(scope, attempt.id))

    original_path = app.history(scope)
    branch_point_id = original_path.messages[1].id
    original_leaf_id = original_path.messages[-1].id
    original_summary = summary_repository.get_current(scope)
    assert original_summary is not None
    assert original_summary.checkpoint_message_id == original_path.messages[3].id

    alternative_ids = []
    for number in range(1, 4):
        responses.chunks = (f"Fourth answer {number}",)
        retry = app.retry_completed_response(scope)
        assert list(app.stream(scope, retry.id)) == [f"Fourth answer {number}"]
        alternative_ids.append(app.history(scope).messages[-1].id)
        exact_prompt = "\n".join(message.content for message in responses.captured[-1])
        assert "Fourth" in exact_prompt
        assert all(
            f"Fourth answer {prior}" not in exact_prompt for prior in range(1, number)
        )

    assert app.retry_availability(scope).retries_remaining == 0
    with pytest.raises(RetryLimitError):
        app.retry_completed_response(scope)

    selected_original = app.select_alternative(
        scope, original_leaf_id, alternative_ids[-1]
    )
    assert selected_original.selected_leaf_id == original_leaf_id
    app.branch_from_here(scope, branch_point_id, original_leaf_id)
    branch_summary = summary_repository.get_current(scope)
    assert branch_summary is not None
    assert branch_summary.id != original_summary.id
    assert branch_summary.checkpoint_message_id == branch_point_id

    responses.chunks = ("The new future disagrees",)
    branched = app.send(scope, SubmittedInput(content="Choose the new future"))
    list(app.stream(scope, branched.id))
    branch_leaf_id = app.history(scope).messages[-1].id
    branch_prompt = "\n".join(message.content for message in responses.captured[-1])
    assert "Durable summary 1" in branch_prompt
    assert "Choose the new future" in branch_prompt
    assert "Second" not in branch_prompt and "Fourth answer" not in branch_prompt

    restarted_responses = FakeResponse()
    restarted = _service(factory, restarted_responses, FakeSummary())
    assert restarted.resume(scope).messages[-1].id == branch_leaf_id
    restarted_responses.chunks = ("Uncommitted fragment",)
    restarted_responses.fail = True
    failed = restarted.send(scope, SubmittedInput(content="Recover this turn"))
    with pytest.raises(ProviderInvocationError, match="Provider failed"):
        list(restarted.stream(scope, failed.id))

    recovered_responses = FakeResponse()
    recovered_responses.chunks = ("Recovered answer",)
    recovered = _service(factory, recovered_responses, FakeSummary())
    incomplete = recovered.resume(scope)
    assert incomplete.attempts[-1].incomplete_output == "Uncommitted fragment"
    continuation = recovered.continue_incomplete_turn(scope)
    assert continuation.user_message_id == failed.user_message_id
    assert list(recovered.stream(scope, continuation.id)) == ["Recovered answer"]
    recovered_branch_leaf_id = recovered.history(scope).messages[-1].id
    recovery_prompt = "\n".join(
        message.content for message in recovered_responses.captured[-1]
    )
    assert "Recover this turn" in recovery_prompt
    assert "Uncommitted fragment" not in recovery_prompt
    assert "Second" not in recovery_prompt and "Fourth answer" not in recovery_prompt

    restored_old = recovered.select_saved_future(
        scope, original_leaf_id, recovered_branch_leaf_id
    )
    assert restored_old.selected_leaf_id == original_leaf_id
    assert summary_repository.get_current(scope) == original_summary
    assert [message.content for message in restored_old.messages] == [
        message.content for message in original_path.messages
    ]
    restored_branch = recovered.select_saved_future(
        scope, recovered_branch_leaf_id, original_leaf_id
    )
    assert restored_branch.selected_leaf_id == recovered_branch_leaf_id

    graph_before_archive = recovered.inspect_graph(scope)
    assert set(alternative_ids).issubset(
        {node.message.id for node in graph_before_archive.nodes}
    )
    assert original_leaf_id in {node.message.id for node in graph_before_archive.nodes}

    for field in (
        "identity_id",
        "persona_id",
        "continuity_id",
        "conversation_id",
    ):
        forged = scope.model_copy(update={field: uuid4()})
        with pytest.raises(ConversationNotFoundError):
            recovered.inspect_graph(forged)
        with pytest.raises(ConversationNotFoundError):
            recovered.retry_completed_response(forged)

    DbContinuityRepository(factory).archive(
        scope.identity_id, scope.persona_id, scope.continuity_id
    )
    archived = recovered.inspect_graph(scope)
    assert archived.selected_leaf_id == recovered_branch_leaf_id
    assert not any(node.branchable for node in archived.nodes)
    with pytest.raises(ArchivedContinuityError):
        recovered.select_saved_future(scope, original_leaf_id, recovered_branch_leaf_id)
    with pytest.raises(ArchivedContinuityError):
        recovered.retry_completed_response(scope)
