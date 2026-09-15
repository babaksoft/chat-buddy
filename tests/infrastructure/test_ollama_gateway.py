from unittest.mock import Mock, patch

from chat_buddy.chat.domain import ChatMessage, ChatRole
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.llm import OllamaGateway


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_uses_chat_settings_by_default(client_type: Mock) -> None:
    gateway = OllamaGateway()

    client_type.assert_called_once_with(host=settings.OLLAMA_ENDPOINT_URL)
    assert gateway._chat_model == settings.CHAT_MODEL
    assert gateway._utility_model == settings.UTILITY_MODEL


@patch("chat_buddy.chat.infrastructure.llm.ollama_gateway.Client")
def test_generate_sends_domain_messages_to_ollama(client_type: Mock) -> None:
    client = client_type.return_value
    client.chat.return_value = {
        "message": {"content": "Hello"},
        "prompt_eval_count": 4,
        "eval_count": 2,
    }
    gateway = OllamaGateway(model_name="chat-model", host="http://ollama.test")

    response = gateway.generate([ChatMessage(role=ChatRole.USER, content="Hi")])

    assert response == "Hello"
    client_type.assert_called_once_with(host="http://ollama.test")
    client.chat.assert_called_once_with(
        model="chat-model",
        messages=[{"role": "user", "content": "Hi"}],
    )
