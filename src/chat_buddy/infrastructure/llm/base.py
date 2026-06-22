from abc import ABC, abstractmethod


class LLMGateway(ABC):
    """Abstract interface for LLM integrations."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
    ) -> str:
        """
        Generate a response from the language model.

        Args:
            prompt:
                User prompt sent to the model.

        Returns:
            Generated model response.
        """
