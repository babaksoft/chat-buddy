import logging

from ollama import Client

from chat_buddy.infrastructure.llm.base import LLMGateway

logger = logging.getLogger(__name__)


class OllamaGateway(LLMGateway):
    """
    Ollama-backed implementation of the LLM gateway.
    """

    def __init__(
        self,
        model_name: str = "samantha-mistral:7b",
        host: str = "http://localhost:11434",
    ) -> None:
        """
        Initialize the Ollama gateway.

        Args:
            model_name:
                Name of the Ollama model.

            host:
                Ollama server endpoint.
        """

        self._model_name = model_name
        self._client = Client(host=host)

    def generate(
        self,
        prompt: str,
    ) -> str:
        """
        Generate a response using Ollama.

        Args:
            prompt:
                Prompt sent to the model.

        Returns:
            Generated response text.
        """

        logger.debug(
            "Generating response using model '%s'.",
            self._model_name,
        )

        response = self._client.chat(
            model=self._model_name,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        content: str = str(response["message"]["content"])

        logger.debug(
            "Generated response (%d characters).",
            len(content),
        )

        return content
