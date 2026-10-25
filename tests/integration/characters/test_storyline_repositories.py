"""Storyline and ordered-scene repository integration coverage."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.domain import (
    ActiveStorylineError,
    ArchivedContinuityError,
    ContinuityLifecycle,
    IdentityDetails,
    IncompleteLatestSceneError,
    InvalidSceneOwnershipError,
    PersonaCore,
    RelationshipIntent,
    RelationshipSelection,
    ResponseStyleSnapshot,
    SceneAppendEligibility,
    SceneDetails,
    StaleStorylineError,
    StartingOrigins,
    StartingRelationship,
    StartStoryline,
)
from chat_buddy.characters.infrastructure.db.models import (
    ConversationModel,
    MessageModel,
    SceneModel,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbIdentityRepository,
    DbPersonaRepository,
    DbSceneRepository,
    DbStorylineRepository,
)


def test_storyline_and_scene_fields_round_trip_with_guarded_updates(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist every public field and enforce metadata revision and setup guards.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    repository, scenes, request = _repositories_and_request(factory)
    storyline, scene = repository.start(request, _relationship())

    assert storyline.name == "Railway Days"
    assert storyline.lifecycle == ContinuityLifecycle.ACTIVE
    assert storyline.relationship == _relationship()
    assert scene.position == 1
    assert scene.details == request.initial_scene
    assert not scene.setup_locked
    assert repository.find_confirmation(request) == (storyline, scene)
    assert repository.find_active(request.identity_id, request.persona_id) == storyline
    assert repository.list_for_pair(
        request.identity_id, request.persona_id
    ).storylines == (storyline,)
    assert scenes.list(storyline).scenes == (scene,)

    renamed = repository.rename(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        "Night Train",
        storyline.revision,
    )
    assert renamed.name == "Night Train"
    assert renamed.revision == 2
    with pytest.raises(StaleStorylineError):
        repository.rename(
            renamed.identity_id,
            renamed.persona_id,
            renamed.id,
            "Stale",
            storyline.revision,
        )

    updated_scene = scenes.rename(scene.scope, scene.id, "Platform", renamed.revision)
    assert updated_scene.details.title == "Platform"
    current = repository.get(renamed.identity_id, renamed.persona_id, renamed.id)
    updated_scene = scenes.replace_setup(
        scene.scope, scene.id, "Rain falls over the platform.", current.revision
    )
    assert updated_scene.details.setup == "Rain falls over the platform."
    locked = scenes.lock_setup(scene.scope, scene.id, None)
    assert locked.setup_locked


def test_active_slot_archive_replacement_and_complete_append_guards(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Release only archived pairs and append after a complete selected exchange.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    repository, scenes, request = _repositories_and_request(factory)
    storyline, first = repository.start(request, _relationship())
    with pytest.raises(ActiveStorylineError):
        repository.start(
            request.model_copy(update={"request_id": uuid4()}), _relationship()
        )

    ineligible = SceneAppendEligibility(
        storyline_id=storyline.id,
        scene_id=first.id,
        expected_storyline_revision=storyline.revision,
        expected_selected_leaf_id=None,
        scene_position=1,
        storyline_lifecycle=storyline.lifecycle,
        is_latest_scene=True,
        has_complete_selected_exchange=False,
        has_unmatched_input=False,
        has_open_attempt=False,
    )
    with pytest.raises(IncompleteLatestSceneError, match="no_complete_exchange"):
        scenes.append_next(_next_scene(), ineligible)

    leaf_id = _complete_exchange(factory, first.scope.conversation_id, storyline.id)
    eligible = ineligible.model_copy(
        update={
            "expected_selected_leaf_id": leaf_id,
            "has_complete_selected_exchange": True,
        }
    )
    sequence = scenes.append_next(_next_scene(), eligible)
    assert tuple(scene.position for scene in sequence.scenes) == (1, 2)
    assert sequence.storyline.revision == 2
    assert sequence.scenes[0].setup_locked
    assert not sequence.scenes[1].setup_locked
    with pytest.raises(StaleStorylineError):
        scenes.append_next(
            _next_scene(),
            eligible.model_copy(
                update={
                    "scene_id": sequence.scenes[-1].id,
                    "scene_position": 2,
                    "expected_selected_leaf_id": None,
                }
            ),
        )

    archived = repository.archive(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        sequence.storyline.revision,
    )
    assert archived.lifecycle == ContinuityLifecycle.ARCHIVED
    assert (
        repository.archive(
            storyline.identity_id,
            storyline.persona_id,
            storyline.id,
            sequence.storyline.revision,
        )
        == archived
    )
    with pytest.raises(ArchivedContinuityError):
        scenes.rename(
            sequence.scenes[-1].scope,
            sequence.scenes[-1].id,
            "Read only",
            archived.revision,
        )

    replacement, _ = repository.start(
        request.model_copy(update={"request_id": uuid4(), "name": "Fresh"}),
        _relationship(),
    )
    assert replacement.id != storyline.id
    assert (
        len(
            repository.list_for_pair(request.identity_id, request.persona_id).storylines
        )
        == 2
    )


def test_scene_reads_reject_foreign_complete_ownership(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Require identity, persona, continuity, and conversation for a scene read.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    repository, scenes, request = _repositories_and_request(characters_session_factory)
    _, scene = repository.start(request, _relationship())
    with pytest.raises(InvalidSceneOwnershipError):
        scenes.get(
            scene.scope.model_copy(update={"conversation_id": uuid4()}), scene.id
        )


def test_database_rejects_wrong_mode_duplicate_order_and_cross_owner_conversation(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Enforce scene mode, immutable position, and complete ownership in storage.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    repository, _, request = _repositories_and_request(factory)
    storyline, scene = repository.start(request, _relationship())
    other_repository, _, other_request = _repositories_and_request(factory)
    _, other_scene = other_repository.start(other_request, _relationship())

    with pytest.raises(IntegrityError), factory() as session, session.begin():
        session.execute(
            update(SceneModel).where(SceneModel.id == scene.id).values(mode="ongoing")
        )
    with pytest.raises(IntegrityError), factory() as session, session.begin():
        session.execute(
            update(SceneModel)
            .where(SceneModel.id == scene.id)
            .values(conversation_id=other_scene.scope.conversation_id)
        )
    with pytest.raises(IntegrityError), factory() as session, session.begin():
        conversation = ConversationModel(
            continuity_id=storyline.id,
            identity_id=storyline.identity_id,
            persona_id=storyline.persona_id,
            mode="storyline",
        )
        session.add(conversation)
        session.flush()
        session.add(
            SceneModel(
                continuity_id=storyline.id,
                identity_id=storyline.identity_id,
                persona_id=storyline.persona_id,
                conversation_id=conversation.id,
                mode="storyline",
                position=scene.position,
                title="Duplicate",
                setup="This position is already owned.",
                response_style=_style().model_dump(mode="json"),
                setup_locked=False,
            )
        )
        session.flush()


def _repositories_and_request(
    factory: sessionmaker[Session],
) -> tuple[DbStorylineRepository, DbSceneRepository, StartStoryline]:
    """Create editable profiles and repository fixtures.

    Args:
        factory:
            Isolated Characters database factory.

    Returns:
        Storyline repository, scene repository, and reviewed request.
    """

    identity = DbIdentityRepository(factory).create(IdentityDetails(name="Traveler"))
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Conductor", definition="A watchful railway conductor.")
    )
    request = StartStoryline(
        request_id=uuid4(),
        identity_id=identity.id,
        persona_id=persona.id,
        identity_revision=identity.revision,
        persona_revision=persona.revision,
        name="Railway Days",
        relationship=RelationshipSelection(intent=RelationshipIntent.PLATONIC),
        initial_scene=SceneDetails(
            title="Arrival",
            setup="They meet beside a train.",
            response_style=_style(),
        ),
    )
    return DbStorylineRepository(factory), DbSceneRepository(factory), request


def _relationship() -> StartingRelationship:
    """Create a resolved starting relationship.

    Returns:
        Immutable relationship snapshot.
    """

    return StartingRelationship(
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
    )


def _style() -> ResponseStyleSnapshot:
    """Create the fixed Stage 6 response style.

    Returns:
        Valid response-style snapshot.
    """

    return ResponseStyleSnapshot(
        name="storyline.default",
        version="1.0.0",
        instruction="Respond naturally within the current scene.",
    )


def _next_scene() -> SceneDetails:
    """Create the second scene details.

    Returns:
        Valid next-scene details.
    """

    return SceneDetails(
        title="Departure",
        setup="The train leaves at midnight.",
        response_style=_style(),
    )


def _complete_exchange(
    factory: sessionmaker[Session], conversation_id: UUID, continuity_id: UUID
) -> UUID:
    """Insert one selected complete exchange for append eligibility.

    Args:
        factory:
            Isolated Characters database factory.
        conversation_id:
            Owned conversation identifier.
        continuity_id:
            Owned Storyline identifier.

    Returns:
        Selected persona leaf identifier.
    """

    now = datetime.now(UTC)
    with factory() as session, session.begin():
        conversation = session.get(ConversationModel, conversation_id)
        assert conversation is not None
        user = MessageModel(
            conversation_id=conversation_id,
            continuity_id=continuity_id,
            role="user",
            content="Are we leaving?",
            parent_id=None,
            created_at=now,
        )
        session.add(user)
        session.flush()
        persona = MessageModel(
            conversation_id=conversation_id,
            continuity_id=continuity_id,
            role="persona",
            content="At midnight.",
            parent_id=user.id,
            response_provenance={"fixture": True},
            created_at=now,
        )
        session.add(persona)
        session.flush()
        conversation.selected_leaf_id = persona.id
        scene = session.scalar(
            select(SceneModel).where(SceneModel.conversation_id == conversation_id)
        )
        assert scene is not None
        scene.setup_locked = True
        return persona.id
