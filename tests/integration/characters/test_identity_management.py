"""Characters identity services exercised through real repositories."""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application import IdentityService
from chat_buddy.characters.domain import (
    FrozenIdentityError,
    IdentityDetails,
    IdentityNotFoundError,
    StaleIdentityError,
)
from chat_buddy.characters.infrastructure.db.models import IdentityModel
from chat_buddy.characters.infrastructure.db.repositories import (
    DbIdentityRepository,
)


@pytest.mark.parametrize("birth_date", [None, date(1990, 4, 5)])
def test_create_inspect_edit_and_reload_round_trip_every_field(
    characters_session_factory: sessionmaker[Session], birth_date: date | None
) -> None:
    """All authored fields survive fresh repository instances and replacements.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
        birth_date:
            Birth date alternative to the authored age.
    """

    service = IdentityService(DbIdentityRepository(characters_session_factory))
    details = IdentityDetails(
        name="Alex",
        gender="nonbinary",
        age=36 if birth_date is None else None,
        birth_date=birth_date,
        pronouns="they/them",
        preferred_address="Alex",
        timezone="Asia/Tehran",
    )
    original = service.create(details)
    assert original.details == details
    assert service.inspect(original.id) == original
    edited = service.edit(original.id, IdentityDetails(name="Sam"), original.revision)
    assert edited.id == original.id
    assert edited.revision == original.revision + 1
    assert original.details == details
    reloaded = IdentityService(DbIdentityRepository(characters_session_factory))
    assert reloaded.inspect(original.id) == edited
    assert edited.details == IdentityDetails(name="Sam")
    with pytest.raises(StaleIdentityError):
        service.edit(original.id, details, original.revision)


def test_default_setup_is_idempotent_and_lists_are_deterministic(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """You is unique, unembellished, and listed before named identities.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
    """

    service = IdentityService(DbIdentityRepository(characters_session_factory))
    z = service.create(IdentityDetails(name="Z"))
    a = service.create(IdentityDetails(name="A"))
    a2 = service.create(IdentityDetails(name="A"))
    default = service.ensure_default()
    assert default.details == IdentityDetails(name="You")
    assert service.ensure_default() == default
    expected = [default, *sorted([a, a2], key=lambda value: value.id), z]
    assert service.list() == expected
    edited = service.edit(default.id, IdentityDetails(name="Me", age=30), 1)
    assert service.ensure_default() == edited
    assert len(service.list()) == 4


def test_frozen_edit_is_rejected_and_duplicate_has_only_authored_fields(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Both service and repository guard freezes; copies are independent.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
    """

    repository = DbIdentityRepository(characters_session_factory)
    service = IdentityService(repository)
    source = service.ensure_default()
    # Slice 3 owns the runtime transition; seed its resulting state here.
    with characters_session_factory() as session, session.begin():
        session.execute(
            update(IdentityModel)
            .where(IdentityModel.id == source.id)
            .values(is_frozen=True)
        )
    frozen = service.inspect(source.id)
    with pytest.raises(FrozenIdentityError):
        service.edit(source.id, IdentityDetails(name="Changed"), source.revision)
    with pytest.raises(FrozenIdentityError):
        repository.replace(source.id, IdentityDetails(name="Changed"), source.revision)
    duplicate = service.duplicate(source.id)
    assert duplicate.id != source.id
    assert duplicate.details == frozen.details
    assert not duplicate.is_frozen and not duplicate.is_default
    assert duplicate.revision == 1
    revised = service.duplicate(source.id, IdentityDetails(name="Someone else"))
    assert revised.details.name == "Someone else"
    assert service.inspect(source.id) == frozen
    service.edit(duplicate.id, IdentityDetails(name="Editable"), 1)


def test_missing_identity_and_repository_stale_writes_have_typed_errors(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Missing ownership and bypassed stale service checks remain explicit.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
    """

    repository = DbIdentityRepository(characters_session_factory)
    service = IdentityService(repository)
    unknown_id = uuid4()
    for operation in (
        lambda: service.inspect(unknown_id),
        lambda: service.duplicate(unknown_id),
        lambda: service.edit(unknown_id, IdentityDetails(name="x"), 1),
        lambda: repository.replace(unknown_id, IdentityDetails(name="x"), 1),
    ):
        with pytest.raises(IdentityNotFoundError):
            operation()
    original = service.create(IdentityDetails(name="x"))
    repository.replace(original.id, IdentityDetails(name="y"), 1)
    with pytest.raises(StaleIdentityError):
        repository.replace(original.id, IdentityDetails(name="z"), 1)
    assert service.inspect(original.id).details.name == "y"


def test_maximum_authored_text_lengths_round_trip(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Persist maximum-length authored text without truncation.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
    """

    service = IdentityService(DbIdentityRepository(characters_session_factory))
    details = IdentityDetails(
        name="n" * 128,
        gender="g" * 64,
        pronouns="p" * 64,
        preferred_address="a" * 128,
        timezone="Asia/Tehran",
    )
    identity = service.create(details)
    assert service.inspect(identity.id).details == details
