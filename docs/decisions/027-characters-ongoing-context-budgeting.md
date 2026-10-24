# ADR 027: Bound Ongoing context with branch-compatible summaries

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stages 4–5
- Refines: ADR 008
- Consistent with: ADR 009

## Context

Ongoing conversations must remain resumable as history grows without sending an
oversized prompt, silently dropping required character context, or admitting
partial output and unselected branches.

## Decision

Build Ongoing response context only from the fully owned selected path. Render it
in this order: persona core, identity, starting relationship, fixed response
presentation, compatible rolling summary, uncovered complete turns, and current
user input. Ongoing includes no extracted long-term memory or scene state.
Unselected nodes, covered turns, incomplete attempts, and partial provider output
are ineligible.

Resolve the effective response model before assembly. Its context window reserves
the effective output allowance and fixed prompt overhead. Persona, identity,
relationship, presentation, a compatible summary when present, the latest complete
turn when present, and current input are mandatory. Admit additional whole turns
from newest to oldest, then render the selected contiguous suffix chronologically.
Never split a turn or truncate a required block. If the mandatory prompt cannot
fit, fail before reserving an attempt or invoking the response provider.

When eligible turns are omitted, advance a rolling summary over the oldest
contiguous uncovered prefix. Summary generation has its own provider capability,
effective configuration, token counter, output reserve, and fixed overhead. It
receives the prior summary and only newly covered complete turns, includes as many
whole turns as fit, and must make monotonic checkpoint progress.

Summary revisions are immutable and retain continuity and conversation ownership,
predecessor, exact persona-message checkpoint, generation provenance, and creation
time. The usable revision is the deepest checkpoint on the selected ancestry, not
a conversation-wide mutable active flag. Covered turns are never also rendered as
recent history, and a sibling checkpoint is never accepted merely because it has
the same depth.

Eligibility, budgeting, summarization, and provider invocation remain separate.
Prompt preparation and attempt reservation compare the same selected leaf.
Summary replacement compares the observed lineage and checkpoint. A stale write,
provider failure, empty result, non-progressing summary, or still-oversized prompt
preserves committed conversation history and the last valid compatible summary,
then returns a recoverable context-capacity failure without response generation.

## Consequences

- Ongoing prompts are deterministic, bounded, and reconstructable after restart.
- Switching branches restores that branch's compatible summary lineage.
- Summary text compresses conversation context but never becomes extracted memory.

## Alternatives considered

- Truncate arbitrary messages or mandatory blocks — rejected because it breaks
  turn meaning and character ownership context.
- Use one conversation-wide current summary — rejected because a summary from an
  unselected future would contaminate another branch.
