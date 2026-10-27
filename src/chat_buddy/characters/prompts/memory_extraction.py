"""Strict prompt assembly for contextual Storyline memory deltas."""

from __future__ import annotations

import json

from chat_buddy.characters.domain import MemorySelectionResult, PromptMessage

MEMORY_DELTA_PROMPT_SCHEMA_VERSION = "1.0.0"

_SYSTEM_INSTRUCTION = """You propose Storyline memory changes as strict JSON.
Use only the block marked [new evidence] as support for every non-empty command.
Older context may resolve references, detect duplication, or identify change, but
facts found only in older context must never become new source claims.
Use only opaque memory and revision identifiers present in the supplied snapshot.
Copy the exact source user/persona identifiers and one supplied occurrence position
into every non-empty command's evidence. Return no_change when no supported durable
fact changes. Never include commentary or fields outside the JSON schema."""


def assemble_memory_extraction_prompt(
    selection: MemorySelectionResult, schema: dict[str, object]
) -> tuple[PromptMessage, ...]:
    """Render strict instructions and one immutable selection snapshot.

    Args:
        selection:
            Exact bounded context selected before provider invocation.
        schema:
            Strict JSON response schema enforced again by the parser.

    Returns:
        Two provider-neutral messages separating policy from snapshot data.
    """

    occurrences = {selection.context.scene}
    occurrences.update(
        memory.current.source.occurrence
        for memory in selection.context.eligible_memories
        if memory.id in selection.included_memory_ids
    )
    ordered_occurrences = sorted(
        occurrences, key=lambda item: (item.position, str(item.scene_id))
    )
    occurrence_lines = "\n".join(
        f"- scene_id={item.scene_id}; position={item.position}"
        for item in ordered_occurrences
    )
    user_content = "\n\n".join(
        (
            "\n".join(
                (
                    "[selection metadata]",
                    f"selection_id={selection.id}",
                    (
                        "source_user_message_id="
                        f"{selection.context.source_turn.user.id}"
                    ),
                    (
                        "source_persona_message_id="
                        f"{selection.context.source_turn.persona.id}"
                    ),
                )
            ),
            f"[allowed occurrence positions]\n{occurrence_lines}",
            "[context and new evidence]\n" + "\n\n".join(selection.prompt),
        )
    )
    system_content = "\n\n".join(
        (
            _SYSTEM_INSTRUCTION,
            "[strict JSON schema]\n"
            + json.dumps(schema, sort_keys=True, separators=(",", ":")),
        )
    )
    return (
        PromptMessage(role="system", content=system_content),
        PromptMessage(role="user", content=user_content),
    )
