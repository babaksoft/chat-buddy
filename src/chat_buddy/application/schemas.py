from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True, frozen=True)
class ChatRequest:
    """
    User chat request.
    """

    conversation_id: UUID | None
    message: str


@dataclass(slots=True, frozen=True)
class ChatResponse:
    """
    Assistant chat response.
    """

    conversation_id: UUID
    response: str


@dataclass(slots=True, frozen=True)
class ChatMessage:
    """
    A message in an existing chat.
    """

    role: ChatRole
    content: str
