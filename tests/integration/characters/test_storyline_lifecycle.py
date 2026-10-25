"""Storyline lifecycle application-service integration coverage."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import ContinuityService, StorylineService
from chat_buddy.characters.domain import (
    ActiveStorylineError,
    ConfirmationConflictError,
    ContinuityLifecycle,
    ContinuityMode,
    IdentityDetails,
    IncompleteLatestSceneError,
    StaleIdentityError,
    StartContinuity,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbConversationRepository,
    DbIdentityRepository,
    DbPersonaRepository,
)
from tests.integration.characters.test_storyline_repositories import (
    _complete_exchange,
    _next_scene,
    _repositories_and_request,
)


def test_storyline_service_manages_reviewed_lifecycle_and_fresh_replacement(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Start, resume, edit, append, archive, and replace through the service.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, scenes, request = _repositories_and_request(factory)
    service = StorylineService(storylines, scenes, DbConversationRepository(factory))
    ongoing = ContinuityService(DbContinuityRepository(factory))
    ongoing.start(
        StartContinuity(
            request_id=uuid4(),
            identity_id=request.identity_id,
            persona_id=request.persona_id,
            identity_revision=request.identity_revision,
            persona_revision=request.persona_revision,
            mode=ContinuityMode.ONGOING,
            relationship=request.relationship,
        )
    )
    assert not ongoing.start_availability(
        request.identity_id, request.persona_id
    ).can_start
    assert service.start_availability(request.identity_id, request.persona_id).can_start

    storyline, first = service.start(request)
    assert storyline.relationship.social == "stranger"
    assert storyline.relationship.origins.social == "default"
    assert service.start(request) == (storyline, first)
    with pytest.raises(ConfirmationConflictError):
        service.start(request.model_copy(update={"name": "Changed confirmation"}))
    assert not service.start_availability(
        request.identity_id, request.persona_id
    ).can_start
    assert service.list_grouped() == (
        service.list_for_pair(request.identity_id, request.persona_id),
    )
    assert service.resume_latest(
        request.identity_id, request.persona_id, storyline.id
    ) == (storyline, first)
    assert DbIdentityRepository(factory).get(request.identity_id).is_frozen
    assert DbPersonaRepository(factory).get(request.persona_id).is_frozen

    with pytest.raises(ActiveStorylineError):
        service.start(request.model_copy(update={"request_id": uuid4()}))
    eligibility = service.append_eligibility(
        request.identity_id, request.persona_id, storyline.id
    )
    assert eligibility.block_reason == "no_complete_exchange"
    with pytest.raises(IncompleteLatestSceneError):
        service.append_next(_next_scene(), eligibility)

    renamed = service.rename(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        "Night Train",
        storyline.revision,
    )
    renamed_scene = service.rename_scene(
        first.scope, first.id, "Platform", renamed.revision
    )
    current, _ = service.resume_latest(
        request.identity_id, request.persona_id, storyline.id
    )
    updated_scene = service.replace_scene_setup(
        first.scope,
        first.id,
        "Rain falls over the platform.",
        current.revision,
    )
    assert renamed_scene.details.title == "Platform"
    assert updated_scene.details.setup == "Rain falls over the platform."

    _complete_exchange(factory, first.scope.conversation_id, storyline.id)
    eligibility = service.append_eligibility(
        request.identity_id, request.persona_id, storyline.id
    )
    assert eligibility.can_append
    sequence = service.append_next(_next_scene(), eligibility)
    assert tuple(scene.position for scene in sequence.scenes) == (1, 2)
    assert (
        service.resume_latest(request.identity_id, request.persona_id, storyline.id)[1]
        == sequence.scenes[-1]
    )

    archived = service.archive(
        storyline.identity_id,
        storyline.persona_id,
        storyline.id,
        sequence.storyline.revision,
    )
    assert archived.lifecycle == ContinuityLifecycle.ARCHIVED
    assert (
        service.archive(
            storyline.identity_id,
            storyline.persona_id,
            storyline.id,
            sequence.storyline.revision,
        )
        == archived
    )
    assert service.start_availability(request.identity_id, request.persona_id).can_start

    replacement, replacement_scene = service.start(
        request.model_copy(update={"request_id": uuid4(), "name": "Independent Return"})
    )
    assert replacement.id != storyline.id
    assert replacement_scene.scope.conversation_id not in {
        scene.scope.conversation_id for scene in sequence.scenes
    }
    assert (
        service.append_eligibility(
            request.identity_id, request.persona_id, replacement.id
        ).block_reason
        == "no_complete_exchange"
    )


def test_storyline_service_rejects_a_stale_reviewed_profile(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Reject a start when a profile changes after the reviewed snapshot.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    storylines, scenes, request = _repositories_and_request(factory)
    identities = DbIdentityRepository(factory)
    identities.replace(
        request.identity_id,
        IdentityDetails(name="Changed Traveler"),
        request.identity_revision,
    )
    service = StorylineService(storylines, scenes, DbConversationRepository(factory))

    with pytest.raises(StaleIdentityError):
        service.start(request)
