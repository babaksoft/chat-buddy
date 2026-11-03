"""Timeline application lifecycle coverage."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import (
    TimelineService,
    default_response_style,
    resolve_starting_relationship,
)
from chat_buddy.characters.domain import (
    ConfirmationConflictError,
    ContinuityMode,
    PersonaCore,
    RelationshipIntent,
    RelationshipSelection,
    ResponseStyle,
    SceneDetails,
    StaleIdentityError,
    StartContinuity,
    StartStoryline,
    TimelineRevisionStatus,
    TimelineStartReview,
    TimelineStartStatus,
)
from chat_buddy.characters.infrastructure.db.repositories import (
    DbContinuityRepository,
    DbIdentityRepository,
    DbPersonaRepository,
    DbStorylineRepository,
    DbTimelineDayRepository,
    DbTimelineRepository,
)


class MutableTimezoneSource:
    """Test timezone source whose current application zone can change.

    Attributes:
        name:
            Current candidate IANA timezone identifier.
        calls:
            Number of times capture consulted the source.
    """

    def __init__(self, name: str) -> None:
        """Initialize the source.

        Args:
            name:
                Initial candidate IANA timezone identifier.
        """

        self.name = name
        self.calls = 0

    def timezone_name(self) -> str:
        """Return the current candidate and record the capture.

        Returns:
            Current candidate IANA timezone identifier.
        """

        self.calls += 1
        return self.name


def test_timeline_service_starts_resumes_and_archives_without_creating_days(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Capture timezone once and keep navigation free of placeholder days.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    identity = identities.ensure_default()
    persona = personas.create(
        PersonaCore(name="Mina", definition="A thoughtful old friend")
    )
    review = _review(identity.id, identity.revision, persona.id, persona.revision)
    source = MutableTimezoneSource("Asia/Tehran")
    service = _service(factory, source)

    started = service.start(review)

    assert started.status == TimelineStartStatus.STARTED
    assert started.timeline is not None
    assert started.timeline.calendar_timezone.name == "Asia/Tehran"
    assert source.calls == 1
    assert identities.get(identity.id).is_frozen
    assert personas.get(persona.id).is_frozen
    assert service.resume(identity.id, persona.id, started.timeline.id).days == ()
    assert service.start_availability(identity.id, persona.id).can_start is False

    source.name = "not/a-zone"
    repeated = service.start(review)
    assert repeated.status == TimelineStartStatus.IDEMPOTENT
    assert repeated.timeline == started.timeline
    assert source.calls == 1

    stale = service.archive(
        identity.id, persona.id, started.timeline.id, started.timeline.revision + 1
    )
    assert stale.status == TimelineRevisionStatus.STALE_REVISION
    archived = service.archive(
        identity.id, persona.id, started.timeline.id, started.timeline.revision
    )
    assert archived.status == TimelineRevisionStatus.UPDATED
    assert archived.timeline.lifecycle.value == "archived"
    assert service.resume(identity.id, persona.id, started.timeline.id).days == ()
    assert service.start_availability(identity.id, persona.id).can_start is True

    repeated_archive = service.archive(
        identity.id, persona.id, started.timeline.id, started.timeline.revision
    )
    assert repeated_archive.status == TimelineRevisionStatus.IDEMPOTENT


def test_timeline_service_rejects_conflicting_confirmation_and_stale_review(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Preserve confirmation equality and reviewed profile revisions.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    identity = identities.ensure_default()
    persona = personas.create(PersonaCore(name="Mina", definition="Patient"))
    review = _review(identity.id, identity.revision, persona.id, persona.revision)
    service = _service(factory, MutableTimezoneSource("UTC"))

    started = service.start(review)
    assert started.status == TimelineStartStatus.STARTED

    with pytest.raises(ConfirmationConflictError):
        service.start(review.model_copy(update={"name": "Changed reuse"}))

    second_persona = personas.create(
        PersonaCore(name="Roya", definition="Direct and observant")
    )
    stale = _review(
        identity.id,
        identity.revision + 1,
        second_persona.id,
        second_persona.revision,
    )
    with pytest.raises(StaleIdentityError):
        service.start(stale)


def test_timeline_service_rejects_invalid_injected_zone_without_side_effects(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Validate the internal zone before freezing profiles or creating state.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    identities = DbIdentityRepository(factory)
    personas = DbPersonaRepository(factory)
    identity = identities.ensure_default()
    persona = personas.create(PersonaCore(name="Mina", definition="Patient"))
    review = _review(identity.id, identity.revision, persona.id, persona.revision)
    service = _service(factory, MutableTimezoneSource("not/a-zone"))

    with pytest.raises(ValidationError, match="valid IANA zone"):
        service.start(review)

    assert identities.get(identity.id).is_frozen is False
    assert personas.get(persona.id).is_frozen is False
    assert service.list_for_pair(identity.id, persona.id).timelines == ()


def test_timeline_active_slot_is_independent_of_ongoing_and_storyline(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Allow all three modes to occupy their own active slot for one pair.

    Args:
        characters_session_factory:
            Isolated Characters database factory.
    """

    factory = characters_session_factory
    identity = DbIdentityRepository(factory).ensure_default()
    persona = DbPersonaRepository(factory).create(
        PersonaCore(name="Mina", definition="Patient")
    )
    relationship = RelationshipSelection(intent=RelationshipIntent.PLATONIC)
    resolved = resolve_starting_relationship(relationship)
    ongoing = DbContinuityRepository(factory).start(
        StartContinuity(
            request_id=uuid4(),
            identity_id=identity.id,
            persona_id=persona.id,
            identity_revision=identity.revision,
            persona_revision=persona.revision,
            relationship=relationship,
        ),
        resolved,
    )
    storyline, _ = DbStorylineRepository(factory).start(
        StartStoryline(
            request_id=uuid4(),
            identity_id=identity.id,
            persona_id=persona.id,
            identity_revision=identity.revision,
            persona_revision=persona.revision,
            name="A Story",
            relationship=relationship,
            initial_scene=SceneDetails(
                title="Meeting",
                setup="They meet beside a quiet station.",
                response_style=ResponseStyle(
                    name="storyline.default",
                    version="1.0.0",
                    instruction="Respond naturally within the current scene.",
                ),
            ),
        ),
        resolved,
    )
    review = _review(identity.id, identity.revision, persona.id, persona.revision)

    timeline = _service(factory, MutableTimezoneSource("UTC")).start(review)

    assert ongoing.mode == ContinuityMode.ONGOING
    assert storyline.lifecycle.value == "active"
    assert timeline.status == TimelineStartStatus.STARTED


def _service(
    factory: sessionmaker[Session], source: MutableTimezoneSource
) -> TimelineService:
    """Build a Timeline service over isolated repositories.

    Args:
        factory:
            Isolated Characters session factory.
        source:
            Injected mutable timezone source.

    Returns:
        Configured Timeline lifecycle service.
    """

    return TimelineService(
        DbTimelineRepository(factory),
        DbTimelineDayRepository(factory),
        source,
    )


def _review(
    identity_id: UUID,
    identity_revision: int,
    persona_id: UUID,
    persona_revision: int,
) -> TimelineStartReview:
    """Build one reviewed Timeline confirmation.

    Args:
        identity_id:
            Reviewed identity identifier.
        identity_revision:
            Reviewed identity revision.
        persona_id:
            Reviewed persona identifier.
        persona_revision:
            Reviewed persona revision.

    Returns:
        Validated confirmation without timezone input.
    """

    return TimelineStartReview.model_validate(
        {
            "request_id": uuid4(),
            "identity_id": identity_id,
            "persona_id": persona_id,
            "identity_revision": identity_revision,
            "persona_revision": persona_revision,
            "name": "Ordinary Days",
            "relationship": RelationshipSelection(intent=RelationshipIntent.PLATONIC),
            "response_style": default_response_style(ContinuityMode.TIMELINE),
        }
    )
