from transformers import AutoTokenizer

from chat_buddy.domain.chat import ChatMessage
from chat_buddy.domain.tokenization import TokenCounter


class MistralTokenCounter(TokenCounter):
    """
    Token counter using the Mistral tokenizer.
    """

    MODEL_NAME = "mistralai/Mistral-7B-Instruct-v0.2"

    def __init__(self) -> None:
        self._tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)

    def count_tokens(
        self,
        messages: list[ChatMessage],
    ) -> int:
        """
        Count tokens in a conversation.

        Args:
            messages:
                Messages to count.

        Returns:
            Total token count.
        """

        if not messages:
            return 0

        text = "\n".join(
            f"{message.role.value}: {message.content}" for message in messages
        )

        return len(self._tokenizer.encode(text))
