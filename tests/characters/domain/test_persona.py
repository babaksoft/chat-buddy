"""Persona authored validation and immutable snapshot contracts."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain.persona import Persona, PersonaCore


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("name", " "),
        ("name", "n" * 129),
        ("definition", "\n"),
        ("definition", "d" * 8193),
        ("traits", " "),
        ("traits", "t" * 4097),
    ],
)
def test_invalid_authored_content_is_rejected(field: str, invalid: str) -> None:
    """Reject blank and oversized supplied content.

    Args:
        field:
            Authored field under validation.
        invalid:
            Invalid replacement text.
    """

    fields = {"name": "A", "definition": "A curious guide", field: invalid}
    with pytest.raises(ValidationError):
        PersonaCore.model_validate(fields)


def test_required_content_and_unknown_state_are_rejected() -> None:
    """Require a definition and prohibit continuity state in a global core."""

    for fields in (
        {"name": "A"},
        {"definition": "Guide"},
        {"name": "A", "definition": "Guide", "relationship": "friend"},
    ):
        with pytest.raises(ValidationError):
            PersonaCore.model_validate(fields)


def test_values_and_snapshots_are_immutable_and_revisions_positive() -> None:
    """Trim authored fields and freeze both nested core and snapshot values."""

    core = PersonaCore(name=" A ", definition=" Guide ", traits=" Curious ")
    persona = Persona(id=uuid4(), core=core)
    assert core.model_dump() == {
        "name": "A",
        "definition": "Guide",
        "traits": "Curious",
    }
    assert persona.revision == 1 and not persona.is_frozen
    for value, field in ((core, "name"), (persona, "revision")):
        with pytest.raises(ValidationError):
            setattr(value, field, "Changed")
    with pytest.raises(ValidationError):
        Persona(id=uuid4(), core=core, revision=0)
