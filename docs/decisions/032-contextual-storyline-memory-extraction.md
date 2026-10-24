# ADR 032: Extract Storyline memory through contextual deltas

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stage 6
- Refines: ADR 008
- Consistent with: ADR 031

## Context

New Storyline evidence often needs prior context for reference resolution and
conflict detection. A model may interpret that evidence, but it must not gain
direct write authority or manufacture facts from older context alone.

## Decision

Extraction begins only after a persona response commits a complete selected turn.
There is one effect per source persona message. It moves from `reserved` to
terminal `no_change` or `applied`; a conflict-only delta is applied. A reserved
effect is retryable only while the continuity is active and its source remains
selected and eligible. Failure leaves it reserved, cannot roll back the visible
turn, and cannot leave partial memory changes.

Context selection and delta extraction are separate versioned Characters
strategies. The selector produces an immutable snapshot ordered as identity and
persona labels, starting relationship, scene setup, compatible summary, recent
selected turns, eligible memories, and the exact source turn marked as new
evidence. Ownership blocks and the source turn are mandatory.

Extraction has its own positive input budget, fixed overhead, and output reserve.
After mandatory blocks, the baseline selector admits a compatible summary, recent
turns newest first, then memories by newest learned position, occurrence position,
and stable identifier. Records remain whole and admitted turns render
chronologically. If mandatory input does not fit, no provider call occurs. The
snapshot records included and omitted identifiers, checkpoints, token counts, and
selector version.

The extractor returns `no_change` alone or a bounded set of `create`, `reinforce`,
`supersede`, and `conflict` operations. Every non-empty operation cites the exact
new source turn and targets only opaque current-memory identifiers supplied in the
snapshot. Learned position is the source scene; occurrence uses only a supplied
existing scene position and cannot be later than learned. Older context may
disambiguate new evidence but cannot independently support a new assertion.

The application validates the complete delta against current state and applies it
atomically. Create cannot collide with a current normalized subject; reinforce
requires unchanged content and distinct evidence; supersede targets only a
supplied active extracted revision; conflict preserves the current revision.
Invented, foreign, omitted, stale, excluded, duplicate, over-limit, unsupported,
or contradictory operations reject the whole delta. Multiple operations cannot
target one lineage or create competing subjects.

Each terminal effect, extracted revision, and evidence link records selector and
extractor names and versions, prompt-schema version, provider and model, effective
configuration, source checkpoint, and creation time. Ranking, confidence, typed
memory, or separate consolidation may be introduced only behind a new strategy
version without changing ownership, evidence, or temporal rules.

These decisions apply only to Storyline. Ongoing remains memory-free, Timeline
behavior remains deferred, and no Chat contract or record is imported.

## Consequences

- A provider can propose interpretation but cannot mutate persistence directly.
- Extraction is reproducible, bounded, idempotent, and independent of response
  completion.
- Prior context improves reconciliation without becoming unsupported evidence.

## Alternatives considered

- Extract from the source turn without context — rejected because references and
  contradictions could not be reconciled reliably.
- Let provider output upsert memory directly — rejected because models do not own
  lifecycle, conflict, evidence, or user-authority rules.
