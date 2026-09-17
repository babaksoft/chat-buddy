# Database settings
DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/chat_buddy"

# LLM settings
OLLAMA_ENDPOINT_URL = "http://172.31.80.1:11434"
OLLAMA_PROVIDER_ID = "ollama"
OLLAMA_PROVIDER_NAME = "Ollama"
CHAT_MODEL = "gpt-oss:20b-cloud"
CHAT_MODELS = (CHAT_MODEL,)
UTILITY_MODEL = "gpt-oss:20b-cloud"
MODEL_CONTEXT_WINDOW = 32_768
PROMPT_OVERHEAD_TOKENS = 64  # Reserved for Ollama system prompt and formatting tokens
SUMMARY_TRIGGER_RATIO = 0.85
MEMORY_EXTRACTION_INTERVAL = 10
