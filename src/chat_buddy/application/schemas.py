from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True, frozen=True)
class ChatRequest:
    """
    User chat request.
    """

    conversation_id: UUID
    message: str


@dataclass(slots=True, frozen=True)
class ChatResponse:
    """
    Assistant chat response.
    """

    response: str
