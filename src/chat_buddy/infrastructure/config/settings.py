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
MODEL_NAME = "samantha-mistral:7b"
MODEL_CONTEXT_WINDOW = 32_768
