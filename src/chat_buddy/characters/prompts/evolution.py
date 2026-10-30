"""Strict prompt assembly for relationship and persona evolution."""

from __future__ import annotations

import json

from chat_buddy.characters.domain import EvolutionSnapshot, PromptMessage

EVOLUTION_PROMPT_SCHEMA_VERSION = "1.0.0"

_SYSTEM_INSTRUCTION = """You propose conservative relationship and persona evolution as strict JSON.
Every command must cite the one-based evidence positions that support it, and the
latest position marked new_source must support or explicitly confirm every command.
Older evidence, memories, and summary context may only help interpret the new source.
Summary context is never evidence. Return an empty commands array when the evidence
is ambiguous, merely polite, hypothetical, or does not establish a durable change.
Never weaken user boundaries, change persona core, invent facts, or infer romance
under platonic intent. Use milestone commands only for explicit unambiguous events.
Use persona adaptations only for continuity-specific behavior, never factual memory.
Copy current values into expected fields. Include no commentary or unknown fields."""


def assemble_evolution_prompt(
    snapshot: EvolutionSnapshot, schema: dict[str, object]
) -> tuple[PromptMessage, ...]:
    """Render policy and exactly one immutable evolution snapshot.

    Args:
        snapshot:
            Bounded authored state, projections, context, and exact evidence.
        schema:
            Strict response schema enforced again after provider invocation.

    Returns:
        Provider-neutral system and user messages.
    """

    payload = snapshot.model_dump(
        mode="json", exclude={"token_count", "budget", "evidence"}
    )
    payload["evidence"] = [
        {
            "position": position,
            "new_source": evidence.reference == snapshot.source,
            **evidence.model_dump(mode="json"),
        }
        for position, evidence in enumerate(snapshot.evidence, start=1)
    ]

    return (
        PromptMessage(
            role="system",
            content="\n\n".join(
                (
                    _SYSTEM_INSTRUCTION,
                    "[strict JSON schema]\n"
                    + json.dumps(schema, sort_keys=True, separators=(",", ":")),
                )
            ),
        ),
        PromptMessage(
            role="user",
            content="[immutable evolution snapshot]\n"
            + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        ),
    )
