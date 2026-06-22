from chat_buddy.infrastructure.config.logging import configure_logging
from chat_buddy.infrastructure.db.models import MessageRole
from chat_buddy.infrastructure.db.repositories import (
    ConversationRepository,
)
from chat_buddy.infrastructure.db.session import SessionLocal


def run_smoke_test() -> None:
    """
    Verify basic repository operations.

    The test performs the following lifecycle:

    1. Create a conversation.
    2. Add user and assistant messages.
    3. Retrieve messages.
    4. Delete the conversation.
    5. Verify cleanup.
    """

    with SessionLocal() as session:
        repository = ConversationRepository(session)

        conversation = repository.create_conversation(
            title="Repository Test",
        )

        repository.add_message(
            conversation.id,
            MessageRole.USER,
            "Hello Samantha",
        )

        repository.add_message(
            conversation.id,
            MessageRole.ASSISTANT,
            "Hello human!",
        )

        messages = repository.get_messages(
            conversation.id,
        )

        print(f"Conversation ID: {conversation.id}")

        for message in messages:
            print(f"{message.role.value}: " f"{message.content}")

        deleted = repository.delete_conversation(
            conversation.id,
        )

        print(f"Conversation deleted: {deleted}")

        conversation_after_delete = repository.get_conversation(
            conversation.id,
        )

        print(
            "Conversation exists after deletion:",
            conversation_after_delete is not None,
        )


if __name__ == "__main__":
    configure_logging()
    run_smoke_test()
