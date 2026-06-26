from chat_buddy.domain.chat import ChatMessage
from chat_buddy.domain.context import ContextBuilder


class DefaultContextBuilder(ContextBuilder):
    """
    Return the conversation unchanged.

    Future implementations will trim,
    summarize or augment the context.
    """

    def build_context(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        return messages
