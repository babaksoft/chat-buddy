from dataclasses import dataclass
from enum import Enum


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True, frozen=True)
class ChatMessage:
    """
    A message in an existing chat.
    """

    role: ChatRole
    content: str
