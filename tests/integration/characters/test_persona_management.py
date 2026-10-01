"""Characters persona services exercised through real repositories."""

from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from chat_buddy.characters.application.persona_service import PersonaService
from chat_buddy.characters.domain.errors import (
    FrozenPersonaError,
    PersonaNotFoundError,
    StalePersonaError,
)
from chat_buddy.characters.domain.persona import PersonaCore
from chat_buddy.characters.infrastructure.db.models import PersonaModel
from chat_buddy.characters.infrastructure.db.repositories.persona_repository import (
    DbPersonaRepository,
)


def test_frozen_edit_is_rejected_and_duplicate_has_only_authored_fields(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Both service and repository guard freezes; copies are independent.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
    """

    repository = DbPersonaRepository(characters_session_factory)
    service = PersonaService(repository)
    source = service.create(
        PersonaCore(name="Original", definition="A patient librarian", traits="Curious")
    )
    source = service.edit(
        source.id, PersonaCore(name="Revised", definition="Guide", traits="Patient"), 1
    )

    # Slice 3 owns the runtime transition; seed its resulting state here.
    with characters_session_factory() as session, session.begin():
        session.execute(
            update(PersonaModel)
            .where(PersonaModel.id == source.id)
            .values(is_frozen=True)
        )
    frozen = service.inspect(source.id)
    with pytest.raises(FrozenPersonaError):
        service.edit(
            source.id,
            PersonaCore(name="Changed", definition="Changed"),
            source.revision,
        )
    with pytest.raises(FrozenPersonaError):
        repository.replace(
            source.id,
            PersonaCore(name="Changed", definition="Changed"),
            source.revision,
        )
    duplicate = service.duplicate(source.id)
    assert duplicate.id != source.id
    assert duplicate.core == frozen.core
    assert not duplicate.is_frozen
    assert duplicate.revision == 1
    revised = service.duplicate(
        source.id, PersonaCore(name="Someone else", definition="Revised")
    )
    assert revised.core == PersonaCore(name="Someone else", definition="Revised")
    assert revised.id != source.id and revised.id != duplicate.id
    assert revised.revision == 1 and not revised.is_frozen
    assert set(duplicate.model_dump()) == {"id", "core", "revision", "is_frozen"}
    assert service.inspect(source.id) == frozen
    service.edit(duplicate.id, PersonaCore(name="Editable", definition="Editable"), 1)


def test_missing_persona_and_repository_stale_writes_have_typed_errors(
    characters_session_factory: sessionmaker[Session],
) -> None:
    """Missing ownership and bypassed stale service checks remain explicit.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
    """

    repository = DbPersonaRepository(characters_session_factory)
    service = PersonaService(repository)
    unknown_id = uuid4()
    for operation in (
        lambda: service.inspect(unknown_id),
        lambda: service.duplicate(unknown_id),
        lambda: service.edit(unknown_id, PersonaCore(name="x", definition="x"), 1),
        lambda: repository.replace(
            unknown_id, PersonaCore(name="x", definition="x"), 1
        ),
    ):
        with pytest.raises(PersonaNotFoundError):
            operation()
    original = service.create(PersonaCore(name="x", definition="x"))
    repository.replace(original.id, PersonaCore(name="y", definition="y"), 1)
    with pytest.raises(StalePersonaError):
        repository.replace(original.id, PersonaCore(name="z", definition="z"), 1)
    assert service.inspect(original.id).core.name == "y"


@pytest.mark.parametrize("traits", [None, "t" * 4096])
def test_authored_edits_round_trip_and_preserve_previous_snapshots(
    characters_session_factory: sessionmaker[Session], traits: str | None
) -> None:
    """Persist every field at its limit, then replace without mutating snapshots.

    Args:
        characters_session_factory:
            Factory for isolated Characters SQLite sessions.
        traits:
            Optional authored traits at their maximum length.
    """

    service = PersonaService(DbPersonaRepository(characters_session_factory))
    core = PersonaCore(name="n" * 128, definition="d" * 8192, traits=traits)
    original = service.create(core)
    assert service.inspect(original.id) == original
    edited = service.edit(original.id, PersonaCore(name="A", definition="New"), 1)
    assert edited.id == original.id and edited.revision == 2
    assert original.core == core
    reloaded = PersonaService(DbPersonaRepository(characters_session_factory))
    assert reloaded.inspect(original.id) == edited
    with pytest.raises(StalePersonaError):
        service.edit(original.id, core, 1)
    same_name = service.create(PersonaCore(name="A", definition="Other"))
    assert service.list() == sorted(
        [edited, same_name], key=lambda value: (value.core.name, value.id)
    )
