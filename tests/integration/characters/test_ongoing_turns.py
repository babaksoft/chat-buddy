"""Durable turns, restarts, isolated context, and incomplete-turn recovery."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ConversationService
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    AttemptConflictError,
    ContextCapacityError,
    ConversationNotFoundError,
    ConversationSettings,
    GenerationConfiguration,
    IncompleteTurnError,
    InvalidProviderResponseError,
    ModelDescriptor,
    ProviderInvocationError,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.models import GenerationAttemptModel
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSummaryRepository,
)
from chat_buddy.characters.infrastructure.llm import (
    ConfiguredModelRegistry,
    OllamaGateway,
    Utf8TokenCounter,
)
from tests.characters_support import FakeResponse, service, start


def test_completed_turn_reloads_with_exact_history_and_provenance(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist a whole turn, restore defaults, and keep previous effective snapshots.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="  Hi\n"))
    assert app.history(scope).messages[0].content == "  Hi\n"
    assert list(app.stream(scope, attempt.id)) == ["Hello", " there"]
    saved = service(factory, gateway).resume(scope)
    assert [m.content for m in saved.messages] == ["  Hi\n", "Hello there"]
    assert [m.sequence for m in saved.messages] == [1, 2]
    assert saved.attempts[0].status == "completed"
    assert saved.attempts[0].generation == attempt.generation
    assert saved.attempts[0].finished_at is not None
    settings = ConversationSettings(
        provider="fake",
        model="second",
        requested=GenerationConfiguration(temperature=0.4),
    )
    app.configure(scope, settings)
    new = service(factory, gateway).send(scope, SubmittedInput(content="Next"))
    assert new.generation.model.model == "second"
    assert new.generation.configuration.temperature == 0.4
    assert list(app.stream(scope, new.id))
    assert app.history(scope).attempts[0] == saved.attempts[0]
    assert gateway.captured[-1][-3].content == "  Hi\n"
    assert app.history(scope).settings == settings
    with pytest.raises(IncompleteTurnError):
        app.continue_incomplete_turn(scope)
    with pytest.raises(AttemptConflictError):
        list(app.stream(scope, attempt.id))
    assert app.history(scope).messages[:2] == saved.messages


@pytest.mark.parametrize("chunks", [(), ("Partial",)])
def test_failed_generation_continues_existing_input_without_partial_context(
    characters_session_factory: sessionmaker[Session], chunks: tuple[str, ...]
) -> None:
    """Recover both pre-output and partial failures with one committed response.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
        chunks:
            Output produced before failure.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    gateway.chunks, gateway.fail = chunks, True
    app = service(factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    with pytest.raises(ProviderInvocationError):
        list(app.stream(scope, attempt.id))
    saved = app.history(scope)
    assert saved.attempts[0].status == "failed"
    assert saved.attempts[0].incomplete_output == "".join(chunks)
    assert len(saved.messages) == 1 and gateway.closed
    with pytest.raises(IncompleteTurnError):
        app.send(scope, SubmittedInput(content="Duplicate"))
    gateway.chunks, gateway.fail = ("Recovered",), False
    restarted = service(factory, gateway)
    continuation = restarted.continue_incomplete_turn(scope)
    assert continuation.user_message_id == attempt.user_message_id
    assert list(restarted.stream(scope, continuation.id)) == ["Recovered"]
    history = restarted.history(scope)
    assert [m.content for m in history.messages] == ["Hi", "Recovered"]
    assert history.attempts[0] == saved.attempts[0]
    assert len(history.attempts) == 2
    assert all(m.content != "Partial" for m in gateway.captured[-1])


def test_consumer_close_and_expired_attempts_are_fenced(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Close streams, preserve live attempts, and interrupt only expired work.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    assert app.resume(scope).attempts[0].status == "pending"
    with pytest.raises(AttemptConflictError):
        app.continue_incomplete_turn(scope)
    stream = app.stream(scope, attempt.id)
    assert next(stream) == "Hello"
    stream.close()
    assert gateway.closed
    assert app.history(scope).attempts[0].status == "interrupted"
    continued = app.continue_incomplete_turn(scope)
    stream = app.stream(scope, continued.id)
    assert next(stream) == "Hello"
    with factory() as session, session.begin():
        session.execute(
            update(GenerationAttemptModel)
            .where(GenerationAttemptModel.id == continued.id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=6))
        )
    assert service(factory, gateway).resume(scope).attempts[-1].status == "interrupted"
    replacement = app.continue_incomplete_turn(scope)
    with pytest.raises(AttemptConflictError):
        next(stream)
    assert list(app.stream(scope, replacement.id))
    assert len(app.history(scope).messages) == 2


def test_pending_abandonment_and_duplicate_consumers_preserve_live_stream(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Fence duplicate consumers and recover a pending attempt never consumed.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    with factory() as session, session.begin():
        session.execute(
            update(GenerationAttemptModel)
            .where(GenerationAttemptModel.id == attempt.id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=6))
        )
    assert app.resume(scope).attempts[0].status == "interrupted"
    continued = app.continue_incomplete_turn(scope)
    stream = app.stream(scope, continued.id)
    assert next(stream) == "Hello"
    with pytest.raises(AttemptConflictError):
        list(app.stream(scope, continued.id))
    assert list(stream) == [" there"]
    assert app.history(scope).attempts[-1].status == "completed"


def test_budget_overflow_commits_nothing_and_calls_no_provider(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject full-history overflow before reserving another attempt.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    with pytest.raises(ContextCapacityError):
        app.send(scope, SubmittedInput(content="X" * 32768))
    assert app.history(scope).messages == ()
    assert app.history(scope).attempts == ()
    assert gateway.captured == []
    first = app.send(scope, SubmittedInput(content="Hi"))
    list(app.stream(scope, first.id))
    saved = app.history(scope)
    with pytest.raises(ContextCapacityError):
        service(factory, gateway, context=256).send(
            scope, SubmittedInput(content="Next")
        )
    assert app.history(scope) == saved


@pytest.mark.parametrize(
    "field", ["identity_id", "persona_id", "continuity_id", "conversation_id"]
)
def test_foreign_ownership_cannot_read_or_generate(
    characters_session_factory: sessionmaker[Session], field: str
) -> None:
    """Reject every foreign scope component and exclude another continuity's input.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
        field:
            Ownership component to forge.
    """

    factory = characters_session_factory
    scope = start(factory)
    foreign = start(factory, "Foreign secret persona")
    gateway = FakeResponse()
    app = service(factory, gateway)
    other = app.send(foreign, SubmittedInput(content="Foreign secret input"))
    list(app.stream(foreign, other.id))
    bad = scope.model_copy(
        update={field: getattr(foreign, field) if field != "identity_id" else uuid4()}
    )
    with pytest.raises(ConversationNotFoundError):
        app.history(bad)
    with pytest.raises(ConversationNotFoundError):
        app.send(bad, SubmittedInput(content="Probe"))
    with pytest.raises(ConversationNotFoundError):
        list(app.stream(scope, other.id))
    attempt = app.send(scope, SubmittedInput(content="Own input"))
    list(app.stream(scope, attempt.id))
    assert "Foreign secret" not in "".join(m.content for m in gateway.captured[-1])
    assert len(app.history(scope).messages) == 2


def test_archive_during_generation_prevents_completion_and_profile_mutation(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Archive after output, then reject progress/completion while retaining evidence.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    identities, personas, continuities = (
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbContinuityRepository(factory),
    )
    original_identity, original_persona = identities.get(
        scope.identity_id
    ), personas.get(scope.persona_id)
    original_state = continuities.get(
        scope.identity_id, scope.persona_id, scope.continuity_id
    ).relationship
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    stream = app.stream(scope, attempt.id)
    assert next(stream) == "Hello"
    continuities.archive(scope.identity_id, scope.persona_id, scope.continuity_id)
    with pytest.raises(ArchivedContinuityError):
        list(stream)
    assert app.history(scope).attempts[0].status == "failed"
    assert len(app.history(scope).messages) == 1
    with pytest.raises(ArchivedContinuityError):
        app.continue_incomplete_turn(scope)
    with pytest.raises(ArchivedContinuityError):
        app.configure(scope, ConversationSettings(provider="fake", model="second"))
    assert identities.get(scope.identity_id) == original_identity
    assert personas.get(scope.persona_id) == original_persona
    assert (
        continuities.get(
            scope.identity_id, scope.persona_id, scope.continuity_id
        ).relationship
        == original_state
    )


def test_user_attempt_and_persona_completion_writes_roll_back_together(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Inject persistence failures after message insertion to prove atomic boundaries.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    repository = DbConversationRepository(factory)

    def fail(mapper: object, connection: object, target: object) -> None:
        """Abort the ledger insertion or terminal update.

        Args:
            mapper:
                SQLAlchemy mapper.
            connection:
                Active transaction connection.
            target:
                Attempt being written.

        Raises:
            RuntimeError:
                Always, to force rollback.
        """

        raise RuntimeError("Injected ledger write failure")

    event.listen(GenerationAttemptModel, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError):
            app.send(scope, SubmittedInput(content="Hi"))
    finally:
        event.remove(GenerationAttemptModel, "before_insert", fail)
    assert app.history(scope).messages == ()
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    repository.claim(scope, attempt.id)
    repository.append(scope, attempt.id, "Answer")
    event.listen(GenerationAttemptModel, "before_update", fail)
    try:
        with pytest.raises(RuntimeError):
            repository.complete(scope, attempt.id)
    finally:
        event.remove(GenerationAttemptModel, "before_update", fail)
    saved = app.history(scope)
    assert len(saved.messages) == 1 and saved.attempts[0].status == "streaming"
    repository.complete(scope, attempt.id)
    assert len(app.history(scope).messages) == 2


def test_mocked_ollama_stream_uses_durable_service_contract(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist a response streamed through the actual adapter with a mocked SDK.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    client = MagicMock()
    client.chat.return_value = iter([{"message": {"content": "Ollama answer"}}])
    with patch(
        "chat_buddy.characters.infrastructure.llm.ollama_gateway.Client",
        return_value=client,
    ):
        gateway = OllamaGateway(host="http://unused")
    model = ModelDescriptor(
        provider="ollama",
        model="local",
        context_tokens=8192,
        output_tokens=128,
        capabilities=frozenset({"response"}),
    )
    models = ConfiguredModelRegistry(
        models=(model,),
        responses={"ollama": gateway},
        summaries={},
        counters={"ollama": Utf8TokenCounter()},
        defaults={"response": ("ollama", "local")},
    )
    app = ConversationService(
        DbConversationRepository(factory),
        DbContinuityRepository(factory),
        DbIdentityRepository(factory),
        DbPersonaRepository(factory),
        DbSummaryRepository(factory),
        models,
    )
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    assert list(app.stream(scope, attempt.id)) == ["Ollama answer"]
    assert app.history(scope).messages[-1].content == "Ollama answer"


def test_empty_provider_output_never_completes_a_turn(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Keep an empty provider result recoverable instead of committing a response.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    gateway.chunks = ()
    app = service(factory, gateway)
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    with pytest.raises(InvalidProviderResponseError):
        list(app.stream(scope, attempt.id))
    assert len(app.history(scope).messages) == 1
    assert app.history(scope).attempts[0].status == "failed"


def test_configuration_change_preserves_pending_attempt_and_fences_stale_preflight(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Apply defaults to the next reservation while preserving already bound settings.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    app = service(factory, gateway)
    pending = app.send(scope, SubmittedInput(content="First"))
    app.configure(scope, ConversationSettings(provider="fake", model="second"))
    list(app.stream(scope, pending.id))
    assert gateway.generations[-1].model.model == "first"
    repository = DbConversationRepository(factory)
    with pytest.raises(AttemptConflictError):
        repository.begin(
            scope,
            pending.generation,
            ConversationSettings(provider="fake", model="first"),
            2,
            SubmittedInput(content="Stale"),
        )
    assert len(app.history(scope).messages) == 2
    next_attempt = app.send(scope, SubmittedInput(content="Next"))
    assert next_attempt.generation.model.model == "second"
    list(app.stream(scope, next_attempt.id))
    assert app.history(scope).attempts[0].generation == pending.generation


def test_lazy_composition_uses_replaceable_characters_capabilities(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Compose production repositories with an injected response-only registry.

    Args:
        characters_session_factory:
            Isolated Characters sessions.
    """

    from chat_buddy.characters.infrastructure import (
        create_conversation_service,
    )
    from tests.characters_support import registry

    factory = characters_session_factory
    scope = start(factory)
    gateway = FakeResponse()
    with patch(
        "chat_buddy.characters.infrastructure.conversation_factory.create_model_registry",
        return_value=registry(gateway),
    ):
        app = create_conversation_service(factory)
    attempt = app.send(scope, SubmittedInput(content="Hi"))
    assert list(app.stream(scope, attempt.id)) == ["Hello", " there"]
    assert app.history(scope).attempts[0].status == "completed"
