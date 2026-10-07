"""Ongoing Streamlit behavior with application-service doubles."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ContextCapacityError,
    ConversationGraphView,
    ConversationHistory,
    EvolutionStrategyId,
    GenerationAttempt,
    GraphNodeView,
    Message,
    MessageNode,
    ProviderInvocationError,
    ResponseProvenance,
    ResponseStyleSnapshot,
    StaleSelectionError,
    SubmittedInput,
)
from chat_buddy.characters.ui import ongoing
from tests.characters_support import FakeResponse, registry


def _render() -> None:
    """Render the isolated Ongoing view with a selected continuity."""

    import streamlit as st

    from chat_buddy.characters.ui.ongoing import render_ongoing

    render_ongoing(st.session_state["selected"])


def _graph_with_controls(service: Mock) -> tuple[MessageNode, MessageNode, MessageNode]:
    """Install a selected two-turn future with one first-turn alternative.

    Args:
        service:
            Conversation application double to configure.

    Returns:
        First selected response, its alternative, and selected leaf.
    """

    history = service.resume.return_value
    scope = history.scope
    generation = service.send.return_value.generation
    started = datetime.now(UTC)
    user_one_id = uuid4()
    user_two_id = uuid4()

    def response(content: str, parent_id: UUID, offset: int) -> MessageNode:
        """Build one immutable persona response.

        Args:
            content:
                Saved response text.
            parent_id:
                Parent user identifier.
            offset:
                Stable creation offset.

        Returns:
            Persona graph node with complete provenance.
        """

        return MessageNode(
            id=uuid4(),
            scope=scope,
            parent_id=parent_id,
            role="persona",
            content=content,
            created_at=started + timedelta(seconds=offset),
            response_provenance=ResponseProvenance(
                generation=generation,
                response_style=ResponseStyleSnapshot(
                    name="ongoing", version="1.0.0", instruction="Respond naturally."
                ),
                evolution_strategy=EvolutionStrategyId(
                    name="baseline", version="1.0.0"
                ),
                attempt_id=uuid4(),
            ),
        )

    user_one = MessageNode(
        id=user_one_id,
        scope=scope,
        parent_id=None,
        role="user",
        content="First question",
        created_at=started,
    )
    selected_one = response("First response", user_one_id, 1)
    alternative = response("Alternative response", user_one_id, 2)
    user_two = MessageNode(
        id=user_two_id,
        scope=scope,
        parent_id=selected_one.id,
        role="user",
        content="Follow up",
        created_at=started + timedelta(seconds=3),
    )
    selected_leaf = response("Current response", user_two_id, 4)
    service.resume.return_value = history.model_copy(
        update={
            "messages": tuple(
                Message(
                    id=node.id,
                    scope=scope,
                    sequence=index,
                    role=node.role,
                    content=node.content,
                    created_at=node.created_at,
                )
                for index, node in enumerate(
                    (user_one, selected_one, user_two, selected_leaf), start=1
                )
            )
        }
    )
    service.inspect_graph.return_value = ConversationGraphView(
        scope=scope,
        selected_leaf_id=selected_leaf.id,
        nodes=(
            GraphNodeView(
                message=user_one,
                alternative_ids=(),
                retry_count=0,
                selected=True,
                selected_leaf=False,
                branchable=False,
            ),
            GraphNodeView(
                message=selected_one,
                alternative_ids=(selected_one.id, alternative.id),
                retry_count=1,
                selected=True,
                selected_leaf=False,
                branchable=True,
            ),
            GraphNodeView(
                message=alternative,
                alternative_ids=(selected_one.id, alternative.id),
                retry_count=1,
                selected=False,
                selected_leaf=False,
                branchable=False,
            ),
            GraphNodeView(
                message=user_two,
                alternative_ids=(),
                retry_count=0,
                selected=True,
                selected_leaf=False,
                branchable=False,
            ),
            GraphNodeView(
                message=selected_leaf,
                alternative_ids=(selected_leaf.id,),
                retry_count=0,
                selected=True,
                selected_leaf=True,
                branchable=False,
            ),
        ),
    )
    return selected_one, alternative, selected_leaf


@pytest.fixture
def conversation_ui() -> Generator[tuple[AppTest, Mock], None, None]:
    """Provide a detached continuity and application double.

    Yields:
        Streamlit app and conversation service double.
    """

    from chat_buddy.characters.domain import (
        Continuity,
        ContinuityLifecycle,
        ContinuityMode,
        ConversationScope,
        RelationshipIntent,
        StartingOrigins,
        StartingRelationship,
    )

    row = Continuity(
        id=uuid4(),
        identity_id=uuid4(),
        persona_id=uuid4(),
        conversation_id=uuid4(),
        mode=ContinuityMode.ONGOING,
        lifecycle=ContinuityLifecycle.ACTIVE,
        relationship=StartingRelationship(
            intent=RelationshipIntent.PLATONIC,
            social="stranger",
            romantic="none",
            dynamic="neutral",
            trust="unknown",
            affection="neutral",
            boundaries=(),
            origins=StartingOrigins(
                social="default",
                romantic="default",
                dynamic="default",
                trust="default",
                affection="default",
                boundaries="default",
            ),
        ),
    )
    scope = ConversationScope(
        identity_id=row.identity_id,
        persona_id=row.persona_id,
        continuity_id=row.id,
        conversation_id=row.conversation_id,
    )
    models = registry(FakeResponse())
    service = Mock(spec=ConversationService)
    service.response_models.return_value = models.list_models()
    generation = models.resolve_default("response")
    from chat_buddy.characters.domain import ConversationSettings

    service.default_settings.return_value = ConversationSettings(
        provider="fake", model="first"
    )
    history = ConversationHistory(scope=scope, settings=None, messages=(), attempts=())
    service.resume.return_value = history
    service.inspect_graph.return_value = ConversationGraphView(
        scope=scope, selected_leaf_id=None, nodes=()
    )
    attempt = GenerationAttempt(
        id=uuid4(),
        scope=scope,
        user_message_id=uuid4(),
        submitted_input="Hi",
        generation=generation,
        status="pending",
        incomplete_output="",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        finished_at=None,
    )
    service.send.return_value = attempt
    service.continue_incomplete_turn.return_value = attempt
    service.stream.side_effect = lambda *args: (chunk for chunk in ("Hello", " there"))
    app = AppTest.from_function(_render)
    app.session_state["selected"] = row
    with patch.object(ongoing, "create_conversation_service", return_value=service):
        yield app, service


def test_send_stream_and_supported_configuration(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Send scoped input, consume chunks, and configure only future attempts.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    app.run()
    assert not app.exception
    app.selectbox[0].set_value(("fake", "second")).run()
    next(w for w in app.text_input if w.label.startswith("Temperature")).set_value(
        "0.4"
    )
    next(b for b in app.button if b.label == "Save generation settings").click().run()
    assert service.configure.call_args.args[1].requested.temperature == 0.4
    assert service.configure.call_args.args[1].model == "second"
    app.chat_input[0].set_value("Hi").run()
    assert not app.exception
    service.send.assert_called_once_with(
        service.resume.return_value.scope, SubmittedInput(content="Hi")
    )
    service.stream.assert_called_once()


@pytest.mark.parametrize("status", ["failed", "interrupted", "pending", "streaming"])
def test_incomplete_output_and_recovery(
    conversation_ui: tuple[AppTest, Mock], status: str
) -> None:
    """Separate partial output and disable sends until the existing tail completes.

    Args:
        conversation_ui:
            App and application double.
        status:
            Saved attempt state.
    """

    app, service = conversation_ui
    attempt = service.send.return_value.model_copy(
        update={"status": status, "incomplete_output": "Partial only"}
    )
    message = Message(
        id=attempt.user_message_id,
        scope=attempt.scope,
        sequence=1,
        role="user",
        content="Hi",
        created_at=attempt.created_at,
    )
    service.resume.return_value = service.resume.return_value.model_copy(
        update={"messages": (message,), "attempts": (attempt,)}
    )
    app.run()
    assert not app.exception
    assert app.chat_input[0].disabled
    assert any(m.value == "Partial only" for m in app.markdown)
    button = next(b for b in app.button if b.label == "Continue incomplete turn")
    assert button.disabled == (status in {"pending", "streaming"})
    if not button.disabled:
        button.click().run()
        service.continue_incomplete_turn.assert_called_once_with(attempt.scope)
        service.send.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        ProviderInvocationError("Provider failed"),
        ContextCapacityError("Summary compression failed"),
    ],
)
def test_recoverable_errors(
    conversation_ui: tuple[AppTest, Mock], error: Exception
) -> None:
    """Surface actionable provider and context failures without crashing.

    Args:
        conversation_ui:
            App and application double.
        error:
            Expected application failure.
    """

    app, service = conversation_ui
    service.send.side_effect = error
    app.run().chat_input[0].set_value("Hi").run()
    assert not app.exception
    assert app.error[0].value == str(error)
    assert app.info


def test_archive_and_scope_switch(conversation_ui: tuple[AppTest, Mock]) -> None:
    """Read archives and discard another continuity's rendered transcript.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    row = app.session_state["selected"]
    attempt = service.send.return_value
    message = Message(
        id=uuid4(),
        scope=attempt.scope,
        sequence=1,
        role="persona",
        content="Saved scoped reply",
        created_at=attempt.created_at,
    )
    service.resume.return_value = service.resume.return_value.model_copy(
        update={"messages": (message,)}
    )
    app.session_state["selected"] = row.model_copy(update={"lifecycle": "archived"})
    app.run()
    assert not app.exception
    assert app.chat_input[0].disabled
    assert any(m.value == message.content for m in app.markdown)
    app.session_state["selected"] = row.model_copy(update={"id": uuid4()})
    service.resume.return_value = service.resume.return_value.model_copy(
        update={"messages": ()}
    )
    app.run()
    assert not any(m.value == message.content for m in app.markdown)
    assert not app.chat_input[0].disabled


def test_saved_model_and_overrides_restore(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Restore persisted settings without overwriting them on resume.

    Args:
        conversation_ui:
            App and application double.
    """

    from chat_buddy.characters.domain import (
        ConversationSettings,
        GenerationConfiguration,
    )

    app, service = conversation_ui
    saved = ConversationSettings(
        provider="fake",
        model="second",
        requested=GenerationConfiguration(temperature=0.7, max_output_tokens=256),
    )
    service.resume.return_value = service.resume.return_value.model_copy(
        update={"settings": saved}
    )
    app.run()
    assert not app.exception
    assert app.selectbox[0].value == ("fake", "second")
    assert (
        next(w for w in app.text_input if w.label.startswith("Temperature")).value
        == "0.7"
    )
    assert (
        next(w for w in app.text_input if w.label.startswith("Max output")).value
        == "256"
    )
    service.configure.assert_not_called()
    service.default_settings.assert_not_called()


def test_stream_chunks_and_partial_failure_are_visible(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Render each accumulated chunk and preserve a visible provider failure.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui

    def failing_stream(*args: object) -> Generator[str, None, None]:
        """Produce partial text followed by a normalized provider failure.

        Args:
            args:
                Supplied ownership and attempt identifier.

        Yields:
            Saved partial chunks.

        Raises:
            ProviderInvocationError:
                After partial output.
        """

        yield "Hello"
        yield " there"
        raise ProviderInvocationError("Connection interrupted")

    service.stream.side_effect = failing_stream
    app.run().chat_input[0].set_value("Hi").run()
    assert not app.exception
    assert any(m.value == "Hello there" for m in app.markdown)
    assert app.error[0].value == "Connection interrupted"
    assert any(b.label == "Reload saved turn" for b in app.button)


def test_graph_controls_show_alternatives_retries_and_provenance(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Render saved alternatives, retry accounting, and immutable provenance.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    _, alternative, selected_leaf = _graph_with_controls(service)
    app.run()
    assert not app.exception
    assert any(m.value == alternative.content for m in app.markdown)
    assert any("1 of 3 retries used" in caption.value for caption in app.caption)
    assert any("fake / first" in caption.value for caption in app.caption)
    assert any("Style: ongoing 1.0.0" in caption.value for caption in app.caption)
    assert any(button.label == "Retry response" for button in app.button)
    assert any(button.label == "Select alternative" for button in app.button)
    assert selected_leaf.content in {message.value for message in app.markdown}


def test_retry_and_alternative_selection_use_exact_observed_state(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Invoke distinct retry and exact-selection actions with scoped state.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    _, alternative, selected_leaf = _graph_with_controls(service)
    app.run()
    next(
        button for button in app.button if button.label == "Select alternative"
    ).click().run()
    service.select_saved_future.assert_called_once_with(
        alternative.scope,
        alternative.id,
        selected_leaf.id,
    )

    service.select_saved_future.reset_mock()
    app.run()
    next(
        button for button in app.button if button.label == "Retry response"
    ).click().run()
    service.retry_completed_response.assert_called_once_with(selected_leaf.scope)
    service.stream.assert_called_once_with(
        selected_leaf.scope, service.retry_completed_response.return_value.id
    )


def test_saved_divergent_future_remains_exactly_selectable(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Expose an off-path leaf without guessing among its ancestors.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    branch_point, _, selected_leaf = _graph_with_controls(service)
    graph = service.inspect_graph.return_value
    created_at = graph.nodes[-1].message.created_at + timedelta(seconds=1)
    future_user = MessageNode(
        id=uuid4(),
        scope=graph.scope,
        parent_id=branch_point.id,
        role="user",
        content="Saved direction",
        created_at=created_at,
    )
    future = selected_leaf.model_copy(
        update={
            "id": uuid4(),
            "parent_id": future_user.id,
            "content": "Saved future response",
            "created_at": created_at + timedelta(seconds=1),
        }
    )
    service.inspect_graph.return_value = graph.model_copy(
        update={
            "nodes": graph.nodes
            + (
                GraphNodeView(
                    message=future_user,
                    alternative_ids=(),
                    retry_count=0,
                    selected=False,
                    selected_leaf=False,
                    branchable=False,
                ),
                GraphNodeView(
                    message=future,
                    alternative_ids=(future.id,),
                    retry_count=0,
                    selected=False,
                    selected_leaf=False,
                    branchable=False,
                ),
            )
        }
    )
    app.run()
    assert any(m.value == future.content for m in app.markdown)
    select_buttons = tuple(
        button for button in app.button if button.label == "Select alternative"
    )
    select_buttons[-1].click().run()
    service.select_saved_future.assert_called_once_with(
        future.scope,
        future.id,
        selected_leaf.id,
    )


def test_branch_requires_confirmation_and_uses_exact_observed_state(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Keep a saved future until a scoped branch action is confirmed.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    branch_point, _, selected_leaf = _graph_with_controls(service)
    app.run()
    branch = next(button for button in app.button if button.label == "Branch from here")
    assert branch.disabled
    app.checkbox[0].set_value(True).run()
    next(
        button for button in app.button if button.label == "Branch from here"
    ).click().run()
    service.branch_from_here.assert_called_once_with(
        branch_point.scope,
        branch_point.id,
        selected_leaf.id,
    )


@pytest.mark.parametrize("blocked_by", ["archive", "attempt"])
def test_graph_writes_are_disabled_for_archives_and_open_attempts(
    conversation_ui: tuple[AppTest, Mock], blocked_by: str
) -> None:
    """Prevent every graph mutation while the selected scope is read-only.

    Args:
        conversation_ui:
            App and application double.
        blocked_by:
            Read-only condition under test.
    """

    app, service = conversation_ui
    _graph_with_controls(service)
    if blocked_by == "archive":
        app.session_state["selected"] = app.session_state["selected"].model_copy(
            update={"lifecycle": "archived"}
        )
    else:
        service.resume.return_value = service.resume.return_value.model_copy(
            update={"attempts": (service.send.return_value,)}
        )
    app.run()
    assert not app.exception
    assert all(
        button.disabled for button in app.button if button.label == "Select alternative"
    )
    assert not any(button.label == "Retry response" for button in app.button)
    assert not any(button.label == "Branch from here" for button in app.button)


def test_stale_selection_reloads_the_saved_graph(
    conversation_ui: tuple[AppTest, Mock],
) -> None:
    """Reload instead of applying an action against a stale selected leaf.

    Args:
        conversation_ui:
            App and application double.
    """

    app, service = conversation_ui
    _graph_with_controls(service)
    service.select_saved_future.side_effect = StaleSelectionError("Selection changed")
    app.run()
    next(
        button for button in app.button if button.label == "Select alternative"
    ).click().run()
    assert not app.exception
    assert service.resume.call_count >= 2
    assert service.inspect_graph.call_count >= 2
