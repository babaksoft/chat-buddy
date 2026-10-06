"""End-to-end acceptance of the independent Stage 4 Ongoing workflow."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    ContinuityService,
    IdentityService,
    PersonaService,
)
from chat_buddy.characters.domain import (
    ArchivedContinuityError,
    Continuity,
    ContinuityNotFoundError,
    ConversationNotFoundError,
    ConversationScope,
    ConversationSettings,
    FrozenIdentityError,
    FrozenPersonaError,
    IdentityDetails,
    PersonaCore,
    ProviderInvocationError,
    RelationshipIntent,
    RelationshipSelection,
    StartContinuity,
    SubmittedInput,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbSummaryRepository,
)
from tests.characters_support import FakeResponse
from tests.integration.characters.test_ongoing_summary_context import (
    FakeSummary,
    _service,
)


def test_stage_four_milestone(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Prove the complete milestone using real persistence and fake providers.

    Args:
        characters_session_factory:
            Isolated Characters database sessions.
    """

    prove_stage_four_milestone(characters_session_factory)


def prove_stage_four_milestone(factory: sessionmaker[Session]) -> None:
    """Exercise setup, confirmation, durable conversation, and isolated replacement.

    Args:
        factory:
            SQLite or disposable PostgreSQL Characters sessions.
    """

    identities = IdentityService(DbIdentityRepository(factory))
    personas = PersonaService(DbPersonaRepository(factory))
    continuities = ContinuityService(DbContinuityRepository(factory))
    summaries = DbSummaryRepository(factory)
    identity = identities.ensure_default()
    assert identities.ensure_default() == identity

    persona = personas.create(PersonaCore(name="Guide", definition="Initial core"))
    identity = identities.edit(
        identity.id,
        IdentityDetails(name="Alex", pronouns="they/them"),
        identity.revision,
    )
    persona = personas.edit(
        persona.id,
        PersonaCore(name="Guide", definition="Reviewed core", traits="Patient"),
        persona.revision,
    )
    request = StartContinuity(
        request_id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        identity_revision=identity.revision,
        persona_revision=persona.revision,
        relationship=RelationshipSelection(
            intent=RelationshipIntent.ESTABLISHED,
            social="close_friend",
            romantic="partner",
        ),
    )
    assert not identities.inspect(identity.id).is_frozen
    assert not personas.inspect(persona.id).is_frozen

    continuity = continuities.start(request)
    assert continuities.start(request) == continuity

    frozen_identity = identities.inspect(identity.id)
    frozen_persona = personas.inspect(persona.id)
    assert frozen_identity.is_frozen and frozen_persona.is_frozen
    assert frozen_identity.details == identity.details
    assert frozen_persona.core == persona.core
    assert frozen_identity.revision == frozen_persona.revision == 2
    assert continuity.relationship.origins.social == "user_selected"
    assert continuity.relationship.origins.romantic == "user_selected"

    scope = _scope(continuity)
    responses, summary_provider = FakeResponse(), FakeSummary()
    app = _service(factory, responses, summary_provider)
    app.configure(scope, ConversationSettings(provider="fake", model="response"))
    for content in ("First", "Second", "Third", "Fourth"):
        attempt = app.send(scope, SubmittedInput(content=content))
        assert list(app.stream(scope, attempt.id)) == ["Hello", " there"]
    saved = app.history(scope)
    summary = summaries.get_current(scope)
    assert summary is not None and summary.revision == 2
    assert summary.scope == scope
    assert summary.checkpoint_message_id == saved.messages[3].id
    assert summary.checkpoint_sequence == 4
    assert summary.predecessor_id is not None
    assert summary.generation.capability == "summary"
    assert summary.generation.model.model == "summary"
    assert len(summary_provider.captured) == 2

    # New service and provider instances retain no browser or provider state.
    responses, summary_provider = FakeResponse(), FakeSummary()
    restarted = _service(factory, responses, summary_provider)
    assert restarted.resume(scope) == saved
    assert summaries.get_current(scope) == summary
    assert continuities.resume(identity.id, persona.id, continuity.id) == continuity
    responses.chunks, responses.fail = ("Uncommitted fragment",), True
    failed = restarted.send(scope, SubmittedInput(content="Fifth"))
    with pytest.raises(ProviderInvocationError):
        list(restarted.stream(scope, failed.id))
    incomplete = restarted.history(scope)
    checkpoint = summaries.get_current(scope)
    assert incomplete.messages[:-1] == saved.messages
    assert incomplete.attempts[-1].status == "failed"
    assert incomplete.attempts[-1].incomplete_output == "Uncommitted fragment"
    responses = FakeResponse()
    recovered = _service(factory, responses, FakeSummary())
    assert recovered.resume(scope) == incomplete
    continued = recovered.continue_incomplete_turn(scope)
    assert continued.user_message_id == failed.user_message_id
    assert list(recovered.stream(scope, continued.id)) == ["Hello", " there"]
    final = recovered.history(scope)
    assert len(final.messages) == 10
    assert final.messages[:8] == saved.messages
    assert final.attempts[-2] == incomplete.attempts[-1]
    assert summaries.get_current(scope) == checkpoint
    assert all("Uncommitted fragment" not in m.content for m in responses.captured[-1])
    assert identities.inspect(identity.id) == frozen_identity
    assert personas.inspect(persona.id) == frozen_persona

    archived = continuities.archive(identity.id, persona.id, continuity.id)
    assert archived.lifecycle == "archived"
    assert recovered.resume(scope) == final
    with pytest.raises(ArchivedContinuityError):
        recovered.send(scope, SubmittedInput(content="After archive"))
    assert final.settings is not None
    with pytest.raises(ArchivedContinuityError):
        recovered.configure(scope, final.settings)
    with pytest.raises(FrozenIdentityError):
        identities.edit(identity.id, identity.details, identity.revision)
    with pytest.raises(FrozenPersonaError):
        personas.edit(persona.id, persona.core, persona.revision)

    other_identity = identities.create(IdentityDetails(name="Other identity"))
    foreign = continuities.start(
        request.model_copy(
            update={
                "request_id": uuid4(),
                "identity_id": other_identity.id,
                "identity_revision": other_identity.revision,
                "relationship": RelationshipSelection(
                    intent=RelationshipIntent.NATURAL
                ),
            }
        )
    )
    duplicate = personas.duplicate(persona.id)
    assert not duplicate.is_frozen and duplicate.revision == 1
    with pytest.raises(FrozenPersonaError):
        personas.edit(persona.id, persona.core, persona.revision)
    fresh = continuities.start(
        request.model_copy(
            update={
                "request_id": uuid4(),
                "relationship": RelationshipSelection(
                    intent=RelationshipIntent.PLATONIC
                ),
            }
        )
    )
    fresh_scope = _scope(fresh)
    assert (
        fresh.id != continuity.id
        and fresh.conversation_id != continuity.conversation_id
    )
    assert fresh.relationship.social == foreign.relationship.social == "stranger"
    assert fresh.relationship.romantic == "none"
    assert fresh.relationship.origins.social == "default"
    assert recovered.history(fresh_scope).messages == ()
    assert recovered.history(fresh_scope).attempts == ()
    assert summaries.get_current(fresh_scope) is None
    assert recovered.history(scope) == final
    assert summaries.get_current(scope) == checkpoint
    assert continuities.resume(identity.id, persona.id, continuity.id) == archived
    assert archived.relationship == continuity.relationship

    # Every ownership component is independently fenced, including same-pair history.
    for field, value in (
        ("identity_id", other_identity.id),
        ("persona_id", duplicate.id),
        ("continuity_id", fresh.id),
        ("conversation_id", fresh.conversation_id),
    ):
        forged = scope.model_copy(update={field: value})
        with pytest.raises(ConversationNotFoundError):
            recovered.resume(forged)
        with pytest.raises(ConversationNotFoundError):
            recovered.send(forged, SubmittedInput(content="Foreign probe"))
        with pytest.raises(ConversationNotFoundError):
            recovered.continue_incomplete_turn(forged)
        with pytest.raises(ConversationNotFoundError):
            summaries.get_current(forged)
    with pytest.raises(ContinuityNotFoundError):
        continuities.archive(other_identity.id, persona.id, continuity.id)
    with pytest.raises(ConversationNotFoundError):
        list(recovered.stream(fresh_scope, continued.id))
    attempt = recovered.send(fresh_scope, SubmittedInput(content="Fresh start"))
    list(recovered.stream(fresh_scope, attempt.id))
    assert [m.content for m in responses.captured[-1][-1:]] == ["Fresh start"]
    assert len(responses.captured[-1]) == 5
    assert recovered.history(scope) == final
    assert identities.inspect(identity.id) == frozen_identity
    assert personas.inspect(persona.id) == frozen_persona


def _scope(continuity: Continuity) -> ConversationScope:
    """Derive full conversation ownership from a confirmed continuity.

    Args:
        continuity:
            Persisted active or archived continuity.

    Returns:
        Its sole conversation scope.
    """

    return ConversationScope(
        identity_id=continuity.identity_id,
        persona_id=continuity.persona_id,
        continuity_id=continuity.id,
        conversation_id=continuity.conversation_id,
    )
