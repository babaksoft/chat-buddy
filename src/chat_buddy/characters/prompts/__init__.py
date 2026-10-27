"""Prompt templates."""

from chat_buddy.characters.prompts.memory_extraction import (
    MEMORY_DELTA_PROMPT_SCHEMA_VERSION,
    assemble_memory_extraction_prompt,
)
from chat_buddy.characters.prompts.ongoing import (
    PROMPT_OVERHEAD_TOKENS,
    assemble_ongoing_prompt,
    assemble_summary_prompt,
)
from chat_buddy.characters.prompts.storyline import (
    assemble_storyline_memory_blocks,
    assemble_storyline_prompt,
)

__all__ = [
    "MEMORY_DELTA_PROMPT_SCHEMA_VERSION",
    "PROMPT_OVERHEAD_TOKENS",
    "assemble_memory_extraction_prompt",
    "assemble_ongoing_prompt",
    "assemble_storyline_memory_blocks",
    "assemble_storyline_prompt",
    "assemble_summary_prompt",
]
