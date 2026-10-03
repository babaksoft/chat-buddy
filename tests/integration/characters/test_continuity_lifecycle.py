"""Real Characters repository lifecycle, atomicity, and ownership acceptance."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ContinuityService
from chat_buddy.characters.domain import (
    ActiveContinuityError,
    ConfirmationConflictError,
    ContinuityLifecycle,
    ContinuityMode,
    ContinuityNotFoundError,
    FrozenIdentityError,
    FrozenPersonaError,
    IdentityDetails,
    IdentityNotFoundError,
    PersonaCore,
    PersonaNotFoundError,
    RelationshipIntent,
    RelationshipSelection,
    StaleIdentityError,
    StalePersonaError,
    StartContinuity,
    UnsupportedContinuityModeError,
)
from chat_buddy.characters.infrastructure.db.models import (
    ContinuityModel,
    ConversationModel,
    StartingRelationshipModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)


def test_start_archive_and_fresh_replacement_preserve_history(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Commit complete start records, freeze profiles, and retain independent archives.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    service = ContinuityService(DbContinuityRepository(factory))
    first = service.start(request)
    assert first.lifecycle == ContinuityLifecycle.ACTIVE
    assert first.relationship.social == "stranger"
    assert first.relationship.romantic == "none"
    assert first.relationship.origins.social == "default"
    assert first.relationship.boundaries == ()
    assert "familiarity" not in first.relationship.model_dump()
    assert "familiarity" not in first.relationship.origins.model_dump()
    assert service.start(request) == first
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    assert identities.get(first.identity_id).is_frozen
    assert personas.get(first.persona_id).is_frozen
    with pytest.raises(FrozenIdentityError):
        identities.replace(first.identity_id, IdentityDetails(name="Changed"), 1)
    with pytest.raises(FrozenPersonaError):
        personas.replace(
            first.persona_id, PersonaCore(name="Changed", definition="Changed"), 1
        )
    with pytest.raises(ActiveContinuityError):
        service.start(request.model_copy(update={"request_id": uuid4()}))
    with pytest.raises(ConfirmationConflictError):
        service.start(request.model_copy(update={"identity_revision": 2}))
    archived = service.archive(first.identity_id, first.persona_id, first.id)
    assert archived.lifecycle == ContinuityLifecycle.ARCHIVED
    assert service.archive(first.identity_id, first.persona_id, first.id) == archived
    assert service.start(request) == archived
    selection = RelationshipSelection(
        intent=RelationshipIntent.ESTABLISHED,
        social="acquaintance",
        romantic="partner",
        dynamic="comfortable",
        trust="trusting",
        affection="warm",
        boundaries=("no_physical_intimacy",),
    )
    second = service.start(
        request.model_copy(update={"request_id": uuid4(), "relationship": selection})
    )
    assert first.id != second.id
    assert first.conversation_id != second.conversation_id
    assert second.relationship.origins.social == "user_selected"
    assert second.relationship.origins.boundaries == "user_selected"
    assert "milestones" not in second.relationship.model_dump()
    assert service.resume(first.identity_id, first.persona_id, first.id) == archived
    assert service.resume(second.identity_id, second.persona_id, second.id) == second
    groups = service.list_grouped()
    assert len(groups) == 1
    assert {row.id for row in groups[0].continuities} == {first.id, second.id}
    for field in ["identity_id", "persona_id", "mode", "relationship"]:
        with pytest.raises(ValidationError):
            setattr(second, field, getattr(first, field))


@pytest.mark.parametrize("already_frozen", [False, True])
def test_failed_start_rolls_back_every_record_and_new_freezes(
    characters_session_factory: sessionmaker[Session], already_frozen: bool
) -> None:
    """Inject child insertion failure after profile freezing and continuity flush.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
        already_frozen:
            Whether prior successful use permanently froze the profiles.
    """

    factory = characters_session_factory
    request = _request(factory)
    service = ContinuityService(DbContinuityRepository(factory))
    if already_frozen:
        prior = service.start(request)
        service.archive(prior.identity_id, prior.persona_id, prior.id)
        request = request.model_copy(update={"request_id": uuid4()})

    def fail_insert(mapper: object, connection: object, target: object) -> None:
        """Simulate failure while storing a starting snapshot.

        Args:
            mapper:
                SQLAlchemy mapper.
            connection:
                Active transactional connection.
            target:
                Starting-state row being inserted.

        Raises:
            RuntimeError:
                Always, to test transaction rollback.
        """

        raise RuntimeError("Injected start failure")

    event.listen(StartingRelationshipModel, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="Injected"):
            service.start(request)
    finally:
        event.remove(StartingRelationshipModel, "before_insert", fail_insert)
    assert (
        DbIdentityRepository(factory).get(request.identity_id).is_frozen
        == already_frozen
    )
    assert (
        DbPersonaRepository(factory).get(request.persona_id).is_frozen == already_frozen
    )
    with factory() as session:
        for model in [ContinuityModel, ConversationModel, StartingRelationshipModel]:
            assert session.scalar(select(func.count()).select_from(model)) == int(
                already_frozen
            )


@pytest.mark.parametrize(
    "field,error",
    [
        ("identity_revision", StaleIdentityError),
        ("persona_revision", StalePersonaError),
        ("identity_id", IdentityNotFoundError),
        ("persona_id", PersonaNotFoundError),
        ("mode", UnsupportedContinuityModeError),
    ],
)
def test_invalid_confirmation_leaves_profiles_editable(
    characters_session_factory: sessionmaker[Session],
    field: str,
    error: type[Exception],
) -> None:
    """Reject stale, missing, and unsupported submissions without any start writes.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
        field:
            Request field to invalidate.
        error:
            Required typed failure.
    """

    factory = characters_session_factory
    request = _request(factory)
    invalid: object = (
        2
        if field.endswith("revision")
        else ContinuityMode.STORYLINE if field == "mode" else uuid4()
    )
    with pytest.raises(error):
        ContinuityService(DbContinuityRepository(factory)).start(
            request.model_copy(update={field: invalid})
        )
    assert not DbIdentityRepository(factory).get(request.identity_id).is_frozen
    assert not DbPersonaRepository(factory).get(request.persona_id).is_frozen
    assert DbContinuityRepository(factory).list() == []


def test_shared_persona_has_isolated_relationships_and_conversations(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Freeze a persona globally while preventing cross-pair read and archive.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    request = _request(factory)
    other_identity = DbIdentityRepository(factory).create(IdentityDetails(name="Other"))
    service = ContinuityService(DbContinuityRepository(factory))
    first = service.start(request)
    second = service.start(
        request.model_copy(
            update={
                "request_id": uuid4(),
                "identity_id": other_identity.id,
                "relationship": RelationshipSelection(
                    intent=RelationshipIntent.NATURAL, social="close_friend"
                ),
            }
        )
    )
    assert first.relationship.social == "stranger"
    assert second.relationship.social == "close_friend"
    assert first.conversation_id != second.conversation_id
    for operation in [service.resume, service.archive]:
        with pytest.raises(ContinuityNotFoundError):
            operation(first.identity_id, first.persona_id, second.id)
        with pytest.raises(ContinuityNotFoundError):
            operation(first.identity_id, uuid4(), first.id)
    assert service.resume(second.identity_id, second.persona_id, second.id) == second
    with pytest.raises(FrozenPersonaError):
        DbPersonaRepository(factory).replace(
            second.persona_id, PersonaCore(name="Edited", definition="Edited"), 1
        )
    child_models: tuple[type[ConversationModel | StartingRelationshipModel], ...] = (
        ConversationModel,
        StartingRelationshipModel,
    )
    for model in child_models:
        with pytest.raises(IntegrityError), factory() as session, session.begin():
            session.execute(
                update(model)
                .where(model.continuity_id == first.id)
                .values(identity_id=other_identity.id)
            )
    assert service.resume(first.identity_id, first.persona_id, first.id) == first


def _request(factory: sessionmaker[Session]) -> StartContinuity:
    """Create editable profiles and a confirmed platonic draft.

    Args:
        factory:
            Isolated Characters database factory.

    Returns:
        A start request using current revisions.
    """

    identity = DbIdentityRepository(factory).ensure_default()
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Guide", definition="Helpful guide")
    )
    return StartContinuity(
        request_id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        identity_revision=identity.revision,
        persona_revision=persona.revision,
        relationship=RelationshipSelection(intent=RelationshipIntent.PLATONIC),
    )


@pytest.mark.parametrize("intent", list(RelationshipIntent))
def test_every_intent_round_trips_with_selection_provenance(
    characters_session_factory: sessionmaker[Session], intent: RelationshipIntent
) -> None:
    """Persist every direction with provenance distinguishing explicit defaults.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
        intent:
            Starting relationship direction.
    """

    request = _request(characters_session_factory)
    selection = RelationshipSelection(
        intent=intent,
        social="stranger",
        romantic="partner" if intent == RelationshipIntent.ESTABLISHED else "none",
        boundaries=(),
    )
    service = ContinuityService(DbContinuityRepository(characters_session_factory))
    created = service.start(request.model_copy(update={"relationship": selection}))
    resumed = service.resume(created.identity_id, created.persona_id, created.id)
    assert resumed == created
    assert resumed.relationship.intent == intent
    assert resumed.relationship.origins.social == "user_selected"
    assert resumed.relationship.origins.romantic == "user_selected"
    assert resumed.relationship.origins.boundaries == "user_selected"
    assert resumed.relationship.origins.dynamic == "default"
    with pytest.raises(ValidationError):
        resumed.relationship.origins.social = "default"
    with pytest.raises(ValidationError):
        resumed.relationship.dynamic = "tense"
