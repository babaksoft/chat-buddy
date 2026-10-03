"""Relationship vocabulary and immutable confirmed ownership contracts."""

from itertools import product
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    ContinuityMode,
    RelationshipIntent,
    RelationshipSelection,
    StartContinuity,
)


@pytest.mark.parametrize(
    "intent,social,romantic",
    list(
        product(
            RelationshipIntent,
            ["stranger", "acquaintance", "casual_friend", "close_friend"],
            ["none", "interest", "dating", "partner", "engaged", "spouse"],
        )
    ),
)
def test_relationship_status_compatibility(
    intent: RelationshipIntent, social: str, romantic: str
) -> None:
    """Validate the full initial intent/social/romantic compatibility table.

    Args:
        intent:
            Selected intent.
        social:
            Selected social value.
        romantic:
            Selected romantic value.
    """

    valid = (intent != RelationshipIntent.PLATONIC or romantic == "none") and (
        intent != RelationshipIntent.ESTABLISHED
        or romantic in {"dating", "partner", "engaged", "spouse"}
    )
    values = {"intent": intent, "social": social, "romantic": romantic}
    if valid:
        assert RelationshipSelection.model_validate(values).romantic == romantic
    else:
        with pytest.raises(ValidationError):
            RelationshipSelection.model_validate(values)


@pytest.mark.parametrize(
    "values",
    [
        {"intent": "established_relationship"},
        {"intent": "established_relationship", "romantic": "partner"},
        {
            "intent": "open_to_romance",
            "romantic": "dating",
            "boundaries": ["no_romance"],
        },
        {
            "intent": "open_to_romance",
            "romantic": "interest",
            "boundaries": ["no_flirting"],
        },
        {"intent": "platonic", "boundaries": ["no_romance", "no_romance"]},
        {"intent": "platonic", "dynamic": "joyful"},
        {"intent": "platonic", "trust": "100"},
        {"intent": "platonic", "familiarity": "unfamiliar"},
        {"intent": "platonic", "dynamic": "affectionate"},
        {"intent": "platonic", "affection": "love"},
        {"intent": "platonic", "boundaries": ["invented"]},
    ],
)
def test_invalid_starting_values_are_rejected(values: dict[str, object]) -> None:
    """Reject incomplete established starts and unknown or conflicting values.

    Args:
        values:
            Invalid submitted relationship inputs.
    """

    with pytest.raises(ValidationError):
        RelationshipSelection.model_validate(values)


def test_confirmed_inputs_are_immutable_and_reserve_modes() -> None:
    """Prevent mutation of profile ownership, revisions, mode, and selection."""

    selection = RelationshipSelection(intent=RelationshipIntent.PLATONIC)
    request = StartContinuity(
        request_id=uuid4(),
        identity_id=uuid4(),
        persona_id=uuid4(),
        identity_revision=1,
        persona_revision=1,
        relationship=selection,
    )
    for field, value in [
        ("identity_id", uuid4()),
        ("persona_id", uuid4()),
        ("mode", ContinuityMode.TIMELINE),
    ]:
        with pytest.raises(ValidationError):
            setattr(request, field, value)
    with pytest.raises(ValidationError):
        selection.intent = RelationshipIntent.NATURAL


@pytest.mark.parametrize(
    "field,value",
    [
        *(
            ("dynamic", value)
            for value in [
                "neutral",
                "comfortable",
                "awkward",
                "tense",
                "estranged",
            ]
        ),
        *(("trust", value) for value in ["unknown", "cautious", "trusting"]),
        *(("affection", value) for value in ["neutral", "warm", "affectionate"]),
        *(
            ("boundaries", (value,))
            for value in ["no_romance", "no_flirting", "no_physical_intimacy"]
        ),
    ],
)
def test_all_supporting_values_are_independent_of_status(
    field: str, value: object
) -> None:
    """Accept qualitative dimensions without inferring social or romantic status.

    Args:
        field:
            Supporting input field.
        value:
            Supported qualitative value.
    """

    selection = RelationshipSelection.model_validate(
        {"intent": "platonic", field: value}
    )
    assert selection.social is None
    assert selection.romantic is None
    assert getattr(selection, field) == value
