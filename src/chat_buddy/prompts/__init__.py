"""
Central package for language model prompts.
"""

from chat_buddy.prompts.memory import EXTRACT_MEMORY_PROMPT
from chat_buddy.prompts.summary import SUMMARIZE_PROMPT

__all__ = [
    "EXTRACT_MEMORY_PROMPT",
    "SUMMARIZE_PROMPT",
]
