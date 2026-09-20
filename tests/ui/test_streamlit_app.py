from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from chat_buddy.chat.application.schemas import (
    ChatRequest,
    GenerationSelection,
    ManagedMemory,
    MemoryManagementOutcome,
    MemoryManagementResult,
    MemoryProvenance,
    MemorySource,
    ModelOption,
    ProviderOption,
)
from chat_buddy.chat.application.service import (
    ChatService,
    ConversationService,
    MemoryManagementService,
)
from chat_buddy.chat.domain import (
    ChatMessage,
    ChatRole,
    ConversationRecord,
    GenerationAttemptRecord,
    GenerationAttemptStatus,
    GenerationConfiguration,
    GenerationParameter,
    MemoryLifecycle,
    MemoryOriginKind,
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
    memories = Mock(spec=MemoryManagementService)
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
    memories.list_memories.return_value = ()
    with patch.object(
        chat_page, "build_services", return_value=(chat, conversations, memories)
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
    chat, conversations, _ = services.return_value
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

    chat, _, _ = services.return_value
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

    chat, _, _ = services.return_value
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

    chat, _, _ = services.return_value
    now = datetime.now(UTC)
    attempt = GenerationAttemptRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        source_user_message_id=uuid4(),
        submitted_user_content="Question",
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
    _, conversations, _ = services.return_value
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
    _, conversations, _ = services.return_value
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


def _managed_memory(
    *,
    lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
    origin: MemoryOriginKind = MemoryOriginKind.EXTRACTED,
    source_available: bool = True,
) -> ManagedMemory:
    """Create a memory read model for Streamlit tests.

    Args:
        lifecycle:
            Current memory state.
        origin:
            Provenance kind displayed by the view.
        source_available:
            Whether extracted source details remain available.

    Returns:
        Complete persistence-neutral memory read model.
    """

    now = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)
    source = (
        MemorySource(
            conversation_id=uuid4(),
            conversation_title="Travel plans",
            user_message_id=uuid4(),
            user_message_content="I prefer train travel.",
            assistant_message_id=uuid4(),
            assistant_message_content="I will remember that.",
            generation_attempt_id=uuid4(),
        )
        if origin is MemoryOriginKind.EXTRACTED and source_available
        else None
    )
    return ManagedMemory(
        id=uuid4(),
        revision_id=uuid4(),
        subject="travel preference",
        content="The user prefers train travel.",
        lifecycle=lifecycle,
        provenance=MemoryProvenance(
            kind=origin,
            source_available=source_available,
            source=source,
            superseded_revision_id=(
                uuid4() if origin is MemoryOriginKind.USER_CORRECTION else None
            ),
            corrected_at=(now if origin is MemoryOriginKind.USER_CORRECTION else None),
        ),
        created_at=now - timedelta(days=1),
        updated_at=now,
    )


def _open_memory(app: AppTest) -> AppTest:
    """Open the Chat-owned memory view.

    Args:
        app:
            Running Streamlit test application.

    Returns:
        Rerun application displaying memory management.
    """

    return app.button(key="chat_memory").click().run()


def test_memory_view_is_reachable_without_a_conversation_and_has_empty_state(
    app: AppTest,
    services: Mock,
) -> None:
    """Verify memory inspection is independent of conversation selection."""

    _, _, memories = services.return_value

    _open_memory(app)

    assert not app.exception
    assert app.session_state["chat_conversation_id"] is None
    assert app.title[0].value == "🧠 Memory"
    assert app.info[0].value == "No Chat memories have been saved yet."
    assert not app.chat_input
    memories.list_memories.assert_called_with()


def test_selected_conversation_can_be_reopened_from_memory(
    app: AppTest,
    conversation_id: UUID,
) -> None:
    """Verify the selected conversation row exits the memory view."""

    app.button(key=f"chat_select_{conversation_id}").click().run()
    _open_memory(app)

    app.button(key=f"chat_select_{conversation_id}").click().run()

    assert not app.exception
    assert app.title[0].value == "💬 Chat"
    assert app.session_state["chat_conversation_id"] == conversation_id
    assert len(app.chat_message) == 2


@pytest.mark.parametrize(
    ("origin", "source_available", "expected_copy"),
    [
        (
            MemoryOriginKind.EXTRACTED,
            True,
            "Origin: extracted from a completed Chat turn",
        ),
        (MemoryOriginKind.USER_CORRECTION, True, "Origin: corrected by you"),
        (
            MemoryOriginKind.EXTRACTED,
            False,
            "The source conversation or turn is no longer available.",
        ),
    ],
)
def test_memory_view_shows_provenance(
    app: AppTest,
    services: Mock,
    origin: MemoryOriginKind,
    source_available: bool,
    expected_copy: str,
) -> None:
    """Verify extracted, corrected, and unavailable origins are inspectable."""

    _, _, memories = services.return_value
    memory = _managed_memory(origin=origin, source_available=source_available)
    memories.list_memories.return_value = (memory,)

    _open_memory(app)

    visible_copy = [element.value for element in (*app.caption, *app.info)]
    assert expected_copy in visible_copy
    assert memory.content in [element.value for element in app.markdown]
    if origin is MemoryOriginKind.EXTRACTED and source_available:
        assert app.expander[0].label == "Source turn"
        assert "Conversation: Travel plans" in [item.value for item in app.caption]


def test_memory_can_be_corrected(
    app: AppTest,
    services: Mock,
) -> None:
    """Verify correction inputs call only the application service and refresh."""

    _, _, memories = services.return_value
    memory = _managed_memory()
    corrected = replace(
        memory,
        revision_id=uuid4(),
        subject="preferred transport",
        content="The user prefers sleeper trains.",
        provenance=replace(
            memory.provenance,
            kind=MemoryOriginKind.USER_CORRECTION,
            source=None,
            superseded_revision_id=memory.revision_id,
            corrected_at=memory.updated_at,
        ),
    )
    memories.list_memories.return_value = (memory,)

    def correct(*args: object, **kwargs: object) -> MemoryManagementResult:
        memories.list_memories.return_value = (corrected,)
        return MemoryManagementResult(MemoryManagementOutcome.UPDATED, corrected)

    memories.correct_memory.side_effect = correct
    _open_memory(app)
    app.button(key=f"chat_memory_edit_{memory.id}").click().run()
    app.text_input(key=f"chat_memory_subject_{memory.id}").set_value(
        " Preferred Transport "
    )
    app.text_area(key=f"chat_memory_content_{memory.id}").set_value(
        "The user prefers sleeper trains."
    )
    app.button(key=f"chat_memory_save_{memory.id}").click().run()

    assert not app.exception
    memories.correct_memory.assert_called_once_with(
        memory.id,
        expected_revision_id=memory.revision_id,
        subject=" Preferred Transport ",
        content="The user prefers sleeper trains.",
    )
    assert corrected.content in [element.value for element in app.markdown]


def test_memory_can_be_excluded_and_reactivated(
    app: AppTest,
    services: Mock,
) -> None:
    """Verify lifecycle controls refresh eligibility at the next boundary."""

    _, _, memories = services.return_value
    active = _managed_memory()
    excluded = replace(active, lifecycle=MemoryLifecycle.EXCLUDED)
    memories.list_memories.return_value = (active,)

    def exclude(*args: object, **kwargs: object) -> MemoryManagementResult:
        memories.list_memories.return_value = (excluded,)
        return MemoryManagementResult(MemoryManagementOutcome.UPDATED, excluded)

    def reactivate(*args: object, **kwargs: object) -> MemoryManagementResult:
        memories.list_memories.return_value = (active,)
        return MemoryManagementResult(MemoryManagementOutcome.UPDATED, active)

    memories.exclude_memory.side_effect = exclude
    memories.reactivate_memory.side_effect = reactivate
    _open_memory(app)
    app.button(key=f"chat_memory_exclude_{active.id}").click().run()

    memories.exclude_memory.assert_called_once_with(
        active.id,
        expected_revision_id=active.revision_id,
    )
    assert "State: excluded" in [item.value for item in app.caption]

    app.button(key=f"chat_memory_reactivate_{active.id}").click().run()

    memories.reactivate_memory.assert_called_once_with(
        active.id,
        expected_revision_id=active.revision_id,
    )
    assert "State: active" in [item.value for item in app.caption]


@pytest.mark.parametrize("confirm", [False, True])
def test_memory_deletion_requires_confirmation(
    app: AppTest,
    services: Mock,
    confirm: bool,
) -> None:
    """Verify permanent deletion is explicit, warned, and cancellable."""

    _, _, memories = services.return_value
    memory = _managed_memory()
    memories.list_memories.return_value = (memory,)

    def delete(*args: object, **kwargs: object) -> MemoryManagementResult:
        memories.list_memories.return_value = ()
        return MemoryManagementResult(MemoryManagementOutcome.UPDATED)

    memories.delete_memory.side_effect = delete
    _open_memory(app)
    app.button(key=f"chat_memory_delete_{memory.id}").click().run()

    assert "This action is irreversible." in app.warning[0].value
    memories.delete_memory.assert_not_called()
    if confirm:
        button_key = f"chat_memory_confirm_delete_{memory.id}"
    else:
        button_key = f"chat_memory_cancel_delete_{memory.id}"
    app.button(key=button_key).click().run()

    assert not app.exception
    if confirm:
        memories.delete_memory.assert_called_once_with(
            memory.id,
            expected_revision_id=memory.revision_id,
        )
        assert app.info[0].value == "No Chat memories have been saved yet."
    else:
        memories.delete_memory.assert_not_called()
        assert app.button(key=f"chat_memory_delete_{memory.id}")
