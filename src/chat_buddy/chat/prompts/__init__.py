"""Prompt templates owned by the Chat area."""

from chat_buddy.chat.prompts.memory import (
    EXTRACT_MEMORY_PROMPT,
    MEMORY_CONTEXT_HEADER,
)
from chat_buddy.chat.prompts.summary import SUMMARIZE_PROMPT
from chat_buddy.chat.prompts.title import GENERATE_TITLE_PROMPT

__all__ = [
    "EXTRACT_MEMORY_PROMPT",
    "GENERATE_TITLE_PROMPT",
    "MEMORY_CONTEXT_HEADER",
    "SUMMARIZE_PROMPT",
]
