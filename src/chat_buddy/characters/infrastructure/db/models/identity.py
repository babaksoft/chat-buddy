"""Characters identity persistence mapping."""

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db import CharactersBase


class IdentityModel(CharactersBase):
    """Persist authored fields, permanent freeze state, and edit revision."""

    __tablename__ = "identities"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_identity_revision"),
        CheckConstraint("age >= 0 AND age <= 130", name="ck_identity_age"),
        CheckConstraint(
            "age IS NULL OR birth_date IS NULL", name="ck_identity_age_date"
        ),
        CheckConstraint(
            "default_key IS NULL OR default_key = 'you'", name="ck_identity_default"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable identity identifier."
    )
    name: Mapped[str] = mapped_column(String(128), doc="Authored display name.")
    gender: Mapped[str | None] = mapped_column(
        String(64), doc="Optional authored gender."
    )
    age: Mapped[int | None] = mapped_column(
        Integer, doc="Optional age instead of birth date."
    )
    birth_date: Mapped[date | None] = mapped_column(
        Date, doc="Optional birth date instead of age."
    )
    pronouns: Mapped[str | None] = mapped_column(
        String(64), doc="Optional authored pronouns."
    )
    preferred_address: Mapped[str | None] = mapped_column(
        String(128), doc="Optional preferred form of address."
    )
    timezone: Mapped[str | None] = mapped_column(
        String(64), doc="Optional IANA timezone identifier."
    )
    revision: Mapped[int] = mapped_column(
        Integer, default=1, doc="Monotonic authored edit revision."
    )
    is_frozen: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="Permanent freeze after first continuity use."
    )
    default_key: Mapped[str | None] = mapped_column(
        String(3), unique=True, doc="Unique You slot; null for user-created identities."
    )
