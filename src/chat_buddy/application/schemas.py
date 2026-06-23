from dataclasses import dataclass
from uuid import UUID


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
