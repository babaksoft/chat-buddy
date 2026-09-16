"""Declarative metadata for Characters persistence models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

CHARACTERS_SCHEMA = "characters"


class CharactersBase(DeclarativeBase):
    """Declarative base for future Characters persistence models."""

    metadata = MetaData(schema=CHARACTERS_SCHEMA)
