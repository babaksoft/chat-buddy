from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from chat_buddy.chat.application.schemas import (
    ChatRequest,
    GenerationSelection,
    ModelOption,
    ProviderOption,
)
from chat_buddy.chat.application.service import ChatService, ConversationService
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ConversationRecord,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    GenerationParameter,
    ModelId,
    ProviderId,
)
from chat_buddy.chat.ui import page as chat_page


def _render_app() -> None:
    from chat_buddy.ui.streamlit_app import main

    main()


def _switch_area(app: AppTest, url_path: str) -> AppTest:
    # AppTest.switch_page only supports file-based pages. Simulate the browser's
    # page selection for callable pages while retaining the same session.
    app._page_hash = calc_hash(url_path) if url_path else ""
    return app.run()


@pytest.fixture
def conversation_id() -> UUID:
    return uuid4()


@pytest.fixture
def services(conversation_id: UUID) -> Generator[Mock, None, None]:
    chat = Mock(spec=ChatService)
    conversations = Mock(spec=ConversationService)
    provider_id = ProviderId("local")
    model_id = ModelId("main")
    chat.get_generation_selection.return_value = GenerationSelection(
        providers=(ProviderOption(id=provider_id, display_name="Local"),),
        models=(
            ModelOption(
                provider_id=provider_id,
                id=model_id,
                display_name="Main model",
                supported_generation_parameters=frozenset(GenerationParameter),
            ),
        ),
        provider_id=provider_id,
        model_id=model_id,
        configuration=GenerationConfiguration(),
    )
    chat.get_recoverable_generation_attempts.return_value = ()
    conversations.get_conversations.return_value = [
        ConversationRecord(id=conversation_id, title="Existing conversation")
    ]
    conversations.get_messages.return_value = [
        ChatMessage(role=ChatRole.USER, content="Hello"),
        ChatMessage(role=ChatRole.ASSISTANT, content="Welcome back"),
    ]
    with patch.object(
        chat_page, "build_services", return_value=(chat, conversations)
    ) as factory:
        yield factory


@pytest.fixture
def app(services: Mock) -> AppTest:
    return AppTest.from_function(_render_app, default_timeout=10).run()


def test_chat_is_default_area(app: AppTest, services: Mock) -> None:
    assert not app.exception
    assert app.title[0].value == "💬 Chat"
    assert app.sidebar.header[0].value == "Conversations"
    assert len(app.chat_input) == 1
    services.assert_called_once_with()


def test_characters_opens_without_services(services: Mock) -> None:
    services.side_effect = AssertionError("Characters must not initialize services")
    app = AppTest.from_function(_render_app, default_timeout=10)

    _switch_area(app, "characters")

    assert not app.exception
    assert app.title[0].value == "👥 Characters"
    assert "Character setup and conversations are coming next." in app.markdown[0].value
    assert not app.chat_input
    assert not app.sidebar.header
    assert not app.button
    services.assert_not_called()


def test_selected_conversation_survives_area_switch(
    app: AppTest, services: Mock, conversation_id: UUID
) -> None:
    app.button(key=f"chat_select_{conversation_id}").click().run()
    assert not app.exception
    assert [message.markdown[0].value for message in app.chat_message] == [
        "Hello",
        "Welcome back",
    ]
    services.reset_mock()

    _switch_area(app, "characters")

    assert not app.exception
    assert not app.sidebar.button
    assert not app.chat_message
    assert app.session_state["chat_conversation_id"] == conversation_id
    services.assert_not_called()

    _switch_area(app, "")

    assert not app.exception
    assert app.session_state["chat_conversation_id"] == conversation_id
    assert [message.markdown[0].value for message in app.chat_message] == [
        "Hello",
        "Welcome back",
    ]


def test_new_chat_clears_selection_and_editor(
    app: AppTest, conversation_id: UUID
) -> None:
    app.button(key=f"chat_select_{conversation_id}").click().run()
    app.button(key=f"chat_rename_{conversation_id}").click().run()

    app.button(key="chat_new").click().run()

    assert not app.exception
    assert app.session_state["chat_conversation_id"] is None
    assert app.session_state["chat_editing_conversation_id"] is None
    assert app.session_state["chat_confirming_delete_conversation_id"] is None
    assert not app.chat_message
    assert not app.text_input


@pytest.mark.parametrize("resume", [False, True])
def test_chat_streams_and_selects_resulting_conversation(
    app: AppTest, services: Mock, conversation_id: UUID, resume: bool
) -> None:
    chat, conversations = services.return_value
    if resume:
        app.button(key=f"chat_select_{conversation_id}").click().run()
    chunks: list[str] = []

    def response() -> Generator[str, None, None]:
        for chunk in ["Hello", " there"]:
            chunks.append(chunk)
            yield chunk
        conversations.get_messages.return_value = [
            ChatMessage(role=ChatRole.USER, content="Hi"),
            ChatMessage(role=ChatRole.ASSISTANT, content="Hello there"),
        ]

    chat.stream_chat.return_value = (conversation_id, response())

    app.chat_input[0].set_value("Hi").run()

    assert not app.exception
    chat.stream_chat.assert_called_once_with(
        ChatRequest(conversation_id=conversation_id if resume else None, message="Hi")
    )
    assert chunks == ["Hello", " there"]
    assert app.session_state["chat_conversation_id"] == conversation_id
    assert app.chat_message[-1].markdown[0].value == "Hello there"


def test_new_chat_model_switch_is_persisted_for_next_generation(
    app: AppTest, services: Mock, conversation_id: UUID
) -> None:
    """Verify a new-chat model selection is applied through ChatService."""

    chat, _ = services.return_value
    initial = chat.get_generation_selection.return_value
    other_model = ModelOption(
        provider_id=initial.provider_id,
        id=ModelId("other"),
        display_name="Other model",
        supported_generation_parameters=frozenset(GenerationParameter),
    )
    switched = GenerationSelection(
        providers=initial.providers,
        models=(*initial.models, other_model),
        provider_id=initial.provider_id,
        model_id=other_model.id,
        configuration=initial.configuration,
    )
    chat.get_generation_selection.return_value = GenerationSelection(
        providers=initial.providers,
        models=switched.models,
        provider_id=initial.provider_id,
        model_id=initial.model_id,
        configuration=initial.configuration,
    )

    def update_selection(*args: object) -> UUID:
        chat.get_generation_selection.return_value = switched
        return conversation_id

    chat.update_generation_selection.side_effect = update_selection

    app.run()
    app.selectbox(key="chat_model_new_local").set_value("Other model").run()

    assert not app.exception
    chat.update_generation_selection.assert_called_once_with(
        None,
        ProviderId("local"),
        ModelId("other"),
        GenerationConfiguration(),
    )
    assert app.session_state["chat_conversation_id"] == conversation_id
    assert app.selectbox(key=f"chat_model_{conversation_id}_local").value == "other"


def test_resumed_conversation_restores_persisted_model(
    app: AppTest, services: Mock, conversation_id: UUID
) -> None:
    """Verify selecting a conversation restores its application-owned defaults."""

    chat, _ = services.return_value
    initial = chat.get_generation_selection.return_value
    resumed_model = ModelOption(
        provider_id=initial.provider_id,
        id=ModelId("resumed"),
        display_name="Resumed model",
        supported_generation_parameters=frozenset(GenerationParameter),
    )
    resumed = GenerationSelection(
        providers=initial.providers,
        models=(*initial.models, resumed_model),
        provider_id=initial.provider_id,
        model_id=resumed_model.id,
        configuration=GenerationConfiguration(temperature=0.7),
    )
    chat.get_generation_selection.side_effect = lambda selected_id: (
        resumed if selected_id == conversation_id else initial
    )

    app.button(key=f"chat_select_{conversation_id}").click().run()

    assert not app.exception
    assert app.selectbox(key=f"chat_model_{conversation_id}_local").value == "resumed"
    assert app.number_input(
        key=f"chat_temperature_{conversation_id}_local_resumed"
    ).value == pytest.approx(0.7)
    chat.update_generation_selection.assert_not_called()


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [
        (GenerationAttemptStatus.FAILED, "Provider unavailable"),
        (
            GenerationAttemptStatus.INTERRUPTED,
            "Response generation was interrupted before it completed.",
        ),
    ],
)
def test_incomplete_attempt_is_separate_from_history_and_can_be_retried(
    app: AppTest,
    services: Mock,
    conversation_id: UUID,
    status: GenerationAttemptStatus,
    expected_message: str,
) -> None:
    """Verify failure recovery does not turn partial output into history."""

    chat, _ = services.return_value
    now = datetime.now(UTC)
    attempt = GenerationAttemptRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        source_user_message_id=uuid4(),
        provider_id=ProviderId("local"),
        model_id=ModelId("main"),
        effective_configuration=GenerationConfiguration(),
        status=status,
        created_at=now,
        started_at=now,
        finished_at=now,
        partial_content="Unfinished words",
        error_code=(
            "provider_error" if status is GenerationAttemptStatus.FAILED else None
        ),
        error_detail=(
            "Provider unavailable" if status is GenerationAttemptStatus.FAILED else None
        ),
    )
    chat.get_recoverable_generation_attempts.return_value = (attempt,)
    app.button(key=f"chat_select_{conversation_id}").click().run()

    assert not app.exception
    assert app.warning[0].value == expected_message
    assert "Unfinished words" not in [
        message.markdown[0].value for message in app.chat_message
    ]

    def retry_stream() -> Generator[str, None, None]:
        yield "Recovered response"
        chat.get_recoverable_generation_attempts.return_value = ()

    chat.stream_retry.return_value = (conversation_id, retry_stream())
    app.button(key=f"chat_retry_{attempt.id}").click().run()

    assert not app.exception
    chat.stream_retry.assert_called_once_with(attempt.id)
    assert not app.warning


@pytest.mark.parametrize("action", ["save", "cancel", "blank"])
def test_rename_controls(
    app: AppTest, services: Mock, conversation_id: UUID, action: str
) -> None:
    _, conversations = services.return_value
    app.button(key=f"chat_rename_{conversation_id}").click().run()
    app.text_input[0].set_value("   " if action == "blank" else " Updated title ")
    button = "cancel" if action == "cancel" else "save"
    if action == "save":

        def rename(conversation_id: UUID, title: str) -> bool:
            conversations.get_conversations.return_value = [
                ConversationRecord(id=conversation_id, title=title)
            ]
            return True

        conversations.rename_conversation.side_effect = rename

    app.button(key=f"chat_{button}_{conversation_id}").click().run()

    assert not app.exception
    if action == "save":
        conversations.rename_conversation.assert_called_once_with(
            conversation_id=conversation_id, title="Updated title"
        )
        assert app.button(key=f"chat_select_{conversation_id}").label == "Updated title"
    else:
        conversations.rename_conversation.assert_not_called()
    if action == "blank":
        assert app.toast[0].value == "Title cannot be empty."
        assert len(app.text_input) == 1
    else:
        assert not app.text_input


@pytest.mark.parametrize("confirm", [False, True])
def test_delete_requires_confirmation(
    app: AppTest, services: Mock, conversation_id: UUID, confirm: bool
) -> None:
    _, conversations = services.return_value
    app.button(key=f"chat_select_{conversation_id}").click().run()
    app.button(key=f"chat_delete_{conversation_id}").click().run()
    conversations.delete_conversation.assert_not_called()
    if confirm:

        def delete(conversation_id: UUID) -> bool:
            conversations.get_conversations.return_value = []
            return True

        conversations.delete_conversation.side_effect = delete
    button = "confirm_delete" if confirm else "cancel_delete"

    app.button(key=f"chat_{button}_{conversation_id}").click().run()

    assert not app.exception
    assert app.session_state["chat_confirming_delete_conversation_id"] is None
    if confirm:
        conversations.delete_conversation.assert_called_once_with(
            conversation_id=conversation_id
        )
        assert app.session_state["chat_conversation_id"] is None
        assert not app.chat_message
        assert app.sidebar.caption[0].value == "No conversations yet."
    else:
        conversations.delete_conversation.assert_not_called()
        assert app.session_state["chat_conversation_id"] == conversation_id
        assert len(app.chat_message) == 2
