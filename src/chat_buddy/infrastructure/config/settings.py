import logging
from pathlib import Path

# Global settings
PKG_ROOT = Path(__file__).resolve().parent.parent.parent

LOG_DIR = PKG_ROOT / "logs"
LOG_FILE = LOG_DIR / "chat_buddy.log"
LOG_LEVEL = logging.DEBUG

# Database settings
DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/chat_buddy"

# LLM settings
OLLAMA_ENDPOINT_URL = "http://localhost:11434"
CHAT_MODEL = "samantha-mistral:7b"
UTILITY_MODEL = "llama3.2:3b"
MODEL_CONTEXT_WINDOW = 32_768
PROMPT_OVERHEAD_TOKENS = 64  # Reserved for Ollama system prompt and formatting tokens
SUMMARY_TRIGGER_RATIO = 0.85
MEMORY_EXTRACTION_INTERVAL = 10
