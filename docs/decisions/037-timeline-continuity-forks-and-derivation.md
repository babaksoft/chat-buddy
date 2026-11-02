# ADR 037: Keep Timeline continuity append-only and fork alternate pasts

- Status: Partially superseded by ADR 039
- Date: 2026-11-02
- Scope: Characters, Stage 8
- Refines: ADRs 006, 008, 009, 011, 025, 033, and 035
- Consistent with: ADRs 031, 032, 034, and 036

ADR 039 supersedes every closed-day Timeline fork, profile-duplication, copying,
and identifier-remapping provision in this record. Its continuity ownership,
temporal memory, evolution, and context-eligibility decisions remain accepted.

## Context

Timeline needs an ownership and fork model that preserves local-day history while
remaining consistent with the delivered Storyline graph, memory, and evolution
semantics. Without explicit active-slot, copy, and temporal rules, persistence
could either mix independent relationships or leak knowledge backward in time.

## Decision

A Timeline is an independently owned continuity with exactly one identity, one
persona, one reviewed starting relationship, one automatically captured immutable
calendar timezone, active or archived lifecycle, and optimistic revision. An
identity/persona pair may own at most one active Timeline. Its active Timeline,
Ongoing, and Storyline slots are independent; none shares conversations, memory,
relationship state, or persona adaptation with another mode. Archival is explicit,
permanent, and read-only. It releases only the Timeline slot and a replacement
starts from a newly reviewed relationship without copying continuity-owned state.

Timeline grows only by ADR 011 days in immutable positive position order. The
current open day branches in place under ADRs 009 and 028. A closed day permits
inspection only: retry, alternative selection, and in-place branching are
unavailable. Only Branch from here, naming an exact owned completed persona
message, can create an alternate past.

A closed-day branch from an active Timeline is a reviewed Timeline fork. It leaves
the source unchanged and creates another active Timeline, so its target must be a
distinct profile pair with no active Timeline. As with a Storyline fork, the user
creates that pair by exactly duplicating at least one source profile without
authored changes. The other profile may be the same frozen profile. Fork
confirmation verifies the exact active source revision and branch point, exact
duplicated profile revisions, target-slot availability, and reviewed response-style
settings. It retains the source starting relationship and captured calendar
timezone; it does not invent a new shared past. The target style revision starts
at one and is independent of the source setting.

The fork gives every copied continuity-owned record a new identifier. It copies:

- Each earlier represented day's immutable date and boundary metadata plus only
  its selected message ancestry.
- The branch-point day's metadata and exact ancestry through the named persona
  message, whether that message was selected or off-path in the source.
- The deepest compatible summary lineage and completed-attempt provenance whose
  checkpoints and sources were copied.
- Only eligible active memory lineages and eligible evolution events supported by
  copied evidence, with every ownership, day, message, attempt, summary, evidence,
  and temporal reference remapped to the fork.

It copies no later day, node outside those ancestries, open attempt, unmatched
input, excluded or future memory, unresolved memory conflict, or unsupported
evolution event. No continuity-owned row is shared. The fork retains the source's
captured calendar timezone for future boundaries; copied days keep their original
boundary timezone and UTC facts. Its relationship and persona-adaptation
projections are rebuilt from the source starting relationship and copied eligible
events, then the fork evolves independently.

Timeline memory follows ADRs 031 and 032 with day position replacing scene
position. Every occurrence position is positive and no later than its learned
position. Learned position is the source day. Both positions must be no later than
the target day, and the current-content source checkpoint must be on that day's
selected ancestry or a copied applicable ancestor. Extraction runs only after a
complete selected Timeline turn, cites that exact turn, and retains the same
versioned selection, bounded-delta, validation, conflict, correction, and
idempotency rules as Storyline. Ongoing remains free of extracted long-term memory.

Relationship and persona-adaptation evolution also runs only after an eligible
complete selected turn and cites exact selected evidence. Events are eligible only
when their evidence is selected and its day position is no later than the target
day. Branch selection rebuilds memory eligibility and evolution projections;
switching back restores supported state. The stable validation, correction,
replay, and strategy-version rules in ADRs 034–036 do not change.

Only the target day's selected-path messages, compatible summaries, and current
input are transcript context for a Timeline response. Transcripts and summaries
from prior days never become short-term context. Eligible Timeline memory,
relationship projection, and persona adaptation carry long-term continuity.

## Consequences

- Active-slot constraints remain mode-specific while every continuity stays an
  isolation boundary.
- Immutable day positions, rather than mutable dates or UTC ordering, define
  temporal eligibility.
- A fork is a complete provenance remap, not a second owner pointing at source
  records.
- Calendar gaps do not create memory gaps: earlier eligible derived state remains
  available without including prior-day transcripts.

## Alternatives considered

- Put the fork under the source profile pair — rejected because it would create
  two active Timeline futures in the pair's one active slot.
- Copy profiles and then allow authored edits — rejected because copied history
  would no longer describe the target profiles.
- Include prior-day transcripts in response context — rejected because Timeline
  memory and evolution are the deliberate long-term continuity mechanisms.
- Compare memory by local date — rejected because missing interaction days and
  civil-calendar anomalies can skip dates, while position is the immutable
  continuity order.

## Behavioral examples

| Case | Given | When | Then |
|---|---|---|---|
| Open-day retry | Today's day is open and its selected leaf is a completed persona response. | Retry is reserved. | A new attempt uses the same parent user node and may add a persona sibling in place; no Timeline fork is created. |
| Closed-day fork | Positions 1–4 exist and a persona message in closed position 2 is chosen. | The user reviews an exact profile duplication, free target Timeline slot, and source guard, then confirms Branch from here. | A new Timeline copies position 1's selected ancestry and position 2 through the exact message, retains the source calendar timezone, remaps eligible provenance, copies no positions 3–4, and leaves the source unchanged. |
| Off-path closed fork | The named persona message is a saved alternative outside the closed day's selected path. | The reviewed fork commits. | Earlier days use their selected ancestries; the branch-point day uses the named alternative's exact ancestry. |
| Temporal memory | A fact occurs at position 2 and is learned from selected evidence at position 3. | Context is assembled for positions 2, 3, and 4. | It is ineligible at 2 and eligible at 3 and 4 while its source ancestry remains selected. |
| Branch rebuild | An evolution event is supported only by a persona alternative in today's open day. | Another alternative is selected. | The event becomes inactive and projections replay without it; selecting its ancestry again restores it. |

