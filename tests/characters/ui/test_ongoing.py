"""Ongoing Streamlit behavior with application-service doubles."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ContextCapacityError,
    ConversationHistory,
    GenerationAttempt,
    Message,
    ProviderInvocationError,
    SubmittedInput,
)
from chat_buddy.characters.ui import ongoing
from tests.characters_support import FakeResponse, registry


def _render() -> None:
    """Render the isolated Ongoing view with a selected continuity."""

    import streamlit as st

    from chat_buddy.characters.ui.ongoing import render_ongoing

    render_ongoing(st.session_state["selected"])


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
