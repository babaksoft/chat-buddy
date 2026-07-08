from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ExtractedMemory:
    """
    A memory extracted from conversation messages.
    """

    key: str
    value: str
