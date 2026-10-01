"""Characters persona persistence mapping."""

from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from chat_buddy.characters.infrastructure.db.base import CharactersBase


class PersonaModel(CharactersBase):
    """Persist global authored cores, revision, and permanent freeze state."""

    __tablename__ = "personas"
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_persona_revision"),)

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, doc="Stable persona identifier."
    )
    name: Mapped[str] = mapped_column(String(128), doc="Authored display name.")
    definition: Mapped[str] = mapped_column(
        String(8192), doc="Authored character definition."
    )
    traits: Mapped[str | None] = mapped_column(
        String(4096), doc="Optional authored long-term traits."
    )
    revision: Mapped[int] = mapped_column(
        Integer, default=1, doc="Monotonic authored edit revision."
    )
    is_frozen: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="Permanent global freeze after first use."
    )
