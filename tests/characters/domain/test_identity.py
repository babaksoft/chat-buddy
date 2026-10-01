"""Validation and immutable identity contracts."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain.identity import Identity, IdentityDetails


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " "},
        {"name": "x" * 129},
        {"age": -1},
        {"age": 131},
        {"age": True},
        {"age": 2.5},
        {"age": "20"},
        {"birth_date": "2020-02-30"},
        {"birth_date": datetime.now(UTC).date() + timedelta(days=1)},
        {"age": 20, "birth_date": date(2000, 1, 1)},
        {"timezone": "Mars/Olympus"},
        {"timezone": "../UTC"},
        {"timezone": ""},
        {"pronouns": " "},
        {"gender": " "},
        {"preferred_address": " "},
        {"unknown": "ignored?"},
    ],
)
def test_invalid_authored_fields_are_rejected(fields: dict[str, Any]) -> None:
    """Reject invalid demographics, names, timezones, and unknown fields.

    Args:
        fields:
            Authored field overrides expected to fail validation.
    """

    with pytest.raises(ValidationError):
        IdentityDetails.model_validate({"name": "Someone", **fields})


def test_values_are_frozen_including_nested_details() -> None:
    """Identity snapshots and authored fields cannot be assigned in place."""

    details = IdentityDetails(name=" You ", timezone="Asia/Tehran")
    identity = Identity(id=uuid4(), details=details)
    assert identity.details.name == "You"
    with pytest.raises(ValidationError):
        details.name = "Other"
    with pytest.raises(ValidationError):
        identity.is_frozen = True


@pytest.mark.parametrize("age", [0, 130])
def test_boundary_ages_are_supported(age: int) -> None:
    """Allow newborn and maximum supported authored ages.

    Args:
        age:
            An authored age at a supported boundary.
    """

    assert IdentityDetails(name="You", age=age).age == age


def test_absent_demographics_remain_unknown() -> None:
    """A name alone is sufficient for Ongoing identity setup."""

    details = IdentityDetails(name="You")
    assert all(
        value is None for key, value in details.model_dump().items() if key != "name"
    )


@pytest.mark.parametrize(
    ("field", "limit"),
    [("name", 128), ("gender", 64), ("pronouns", 64), ("preferred_address", 128)],
)
def test_authored_text_accepts_its_limit_and_rejects_overflow(
    field: str, limit: int
) -> None:
    """Enforce text capacities after trimming surrounding whitespace.

    Args:
        field:
            Authored text field under validation.
        limit:
            Maximum supported character count.
    """

    details = IdentityDetails.model_validate(
        {"name": "You", field: " " + "x" * limit + " "}
    )
    assert getattr(details, field) == "x" * limit
    with pytest.raises(ValidationError) as error:
        IdentityDetails.model_validate({"name": "You", field: "x" * (limit + 1)})
    assert error.value.errors()[0]["type"] == "string_too_long"


def test_timezone_overflow_is_rejected_before_zone_lookup() -> None:
    """Reject oversized timezone identifiers through the text capacity check."""

    with pytest.raises(ValidationError) as error:
        IdentityDetails(name="You", timezone="x" * 65)
    assert error.value.errors()[0]["type"] == "string_too_long"
