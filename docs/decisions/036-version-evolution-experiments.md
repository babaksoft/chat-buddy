# ADR 036: Keep evolution invariants outside versioned experiments

- Status: Accepted
- Date: 2026-10-28
- Scope: Characters, Stage 7
- Refines: ADR 010
- Consistent with: ADRs 032, 034, and 035

## Context

Evolution strategies and calibration will improve over time. Replaceability must
not make ownership, user authority, evidence, or replay semantics experimental.

## Decision

Keep these stable product invariants:

- Continuity ownership, selected-history eligibility, exact provenance, and
  deterministic replay.
- Immutable persona core and user-controlled boundaries.
- Separation of memory, relationship state, persona adaptation, and current state.
- Application validation, bounded atomic proposals, append-only events,
  correction by new event, and idempotency per source checkpoint.
- No evolution for archived continuities and no Characters dependency on Chat.
- Explicit narrative evidence for major romantic milestones.

Version evidence selection, proposal prompts, providers, strategy
implementations, accepted adaptation facets, gradual-change thresholds, and
evaluation rubrics. Every effect records its selector, strategy, policy,
prompt-schema, provider, and model versions. Experiments cannot relax stable
invariants; uncertainty produces no change.

The following ADR examples seed the first deterministic scenario inventory:

| Scenario | Tags | Expected behavior |
|---|---|---|
| Platonic warmth | `friendship`, `intent` | Warmth may support friendship, never romance under platonic intent. |
| Gradual trust | `friendship`, `threshold` | Two compatible turns may advance trust; one ambiguous turn does not. |
| Romantic milestone | `romance`, `milestone` | An explicit event may support the exact permitted transition. |
| Temporary conflict | `conflict`, `dynamic` | Conflict may change dynamic without erasing durable status. |
| Adaptation or memory | `adaptation`, `memory` | Facts remain memory; supported behavioral change is adaptation. |
| User correction | `correction`, `replay` | A new event corrects the projection without rewriting history. |
| Retry selection | `branch`, `retry` | Only events supported by selected ancestry remain active. |
| Fresh continuity | `isolation`, `fresh-start` | No prior event, memory, or adaptation is inherited. |

## Consequences

- Strategies can be compared without changing hard safety and ownership rules.
- Evaluation scenarios remain framework-neutral and deterministic.
- Exact configuration provenance makes experiment results reproducible.

## Alternatives considered

- Let each strategy define its own validation — rejected because experiments could
  bypass product invariants.
- Promote strategies from qualitative inspection alone — rejected because hard
  invariants and replay behavior require deterministic gates.

