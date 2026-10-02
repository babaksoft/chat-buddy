"""Immutable authored identity values."""

from datetime import UTC, date, datetime
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IdentityDetails(BaseModel):
    """Validated authored fields; omitted demographics remain unknown.

    Attributes:
        name:
            Required authored display name.
        gender:
            Optional authored gender without an inferred default.
        age:
            Optional integer age from 0 through 130, instead of a birth date.
        birth_date:
            Optional birth date no later than today in UTC, instead of age.
        pronouns:
            Optional authored pronouns.
        preferred_address:
            Optional preferred form of address.
        timezone:
            Optional installed IANA timezone identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1, max_length=128, description="Required authored display name."
    )
    gender: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Optional authored gender.",
    )
    age: int | None = Field(
        default=None,
        ge=0,
        le=130,
        strict=True,
        description="Optional integer age instead of a birth date.",
    )
    birth_date: date | None = Field(
        default=None, description="Optional birth date instead of an age."
    )
    pronouns: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Optional authored pronouns.",
    )
    preferred_address: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional preferred form of address.",
    )
    timezone: str | None = Field(
        default=None,
        max_length=64,
        description="Optional installed IANA timezone identifier.",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        """Require an installed IANA zone name when supplied.

        Args:
            value:
                Optional local timezone identifier.

        Returns:
            The validated identifier.

        Raises:
            ValueError:
                If the identifier is not an IANA zone.
        """

        if value is not None:
            if value not in available_timezones():
                raise ValueError("Timezone must be a valid IANA zone")
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("Timezone must be a valid IANA zone") from error
        return value

    @model_validator(mode="after")
    def validate_age_and_birth_date(self) -> Self:
        """Reject conflicting age inputs and future birth dates.

        Returns:
            This validated value.

        Raises:
            ValueError:
                If both alternatives or a future date are supplied.
        """

        if self.age is not None and self.birth_date is not None:
            raise ValueError("Supply age or birth date, not both")
        if self.birth_date is not None and self.birth_date > datetime.now(UTC).date():
            raise ValueError("Birth date cannot be in the future")
        return self


class Identity(BaseModel):
    """Immutable snapshot with stable ownership and edit revision.

    Attributes:
        id:
            Stable identity identifier preserved across authored edits.
        details:
            Validated immutable authored identity fields.
        revision:
            Positive authored revision used to reject stale edits.
        is_frozen:
            Whether first continuity use permanently forbids authored edits.
        is_default:
            Whether this identity occupies the unique default You slot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(description="Stable identity identifier.")
    details: IdentityDetails = Field(description="Immutable authored identity fields.")
    revision: int = Field(
        default=1, ge=1, description="Positive authored edit revision."
    )
    is_frozen: bool = Field(
        default=False, description="Permanent freeze after first continuity use."
    )
    is_default: bool = Field(
        default=False, description="Designation of the unique default You identity."
    )
