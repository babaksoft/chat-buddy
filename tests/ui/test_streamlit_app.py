from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from chat_buddy.application.schemas import ChatRequest, ConversationEntry
from chat_buddy.application.service import ChatService, ConversationService
from chat_buddy.domain import ChatMessage, ChatRole
from chat_buddy.ui import streamlit_app


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
    conversations.get_conversations.return_value = [
        ConversationEntry(id=conversation_id, title="Existing conversation")
    ]
    conversations.get_messages.return_value = [
        ChatMessage(role=ChatRole.USER, content="Hello"),
        ChatMessage(role=ChatRole.ASSISTANT, content="Welcome back"),
    ]
    with patch.object(
        streamlit_app, "build_services", return_value=(chat, conversations)
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
                ConversationEntry(id=conversation_id, title=title)
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
