# Stage 5 Execution Plan — Characters retry and branching

Status: In progress

Last updated: 2026-10-06

## Outcome

Turn each Characters conversation into an immutable message graph with one selected
root-to-leaf path. Users can retry the latest completed persona response up to three
times, select an exact saved future, or branch Ongoing from an earlier persona
message without deleting history. Only the selected path may affect prompts,
summaries, or later derivation.

Stage 4 supplies linear Ongoing history, durable attempts, provider provenance,
rolling summaries, and the Streamlit workflow. Stage 5 migrates those records in
place. Storyline and Timeline persistence remain deferred; their policy contract
fails closed with `fork_required` where their future workflows must create a fork.

## Fixed contract

- A message is an immutable node. Its optional parent belongs to the same identity,
  persona, continuity, and conversation. Root children are user messages; roles
  alternate on every edge; siblings are alternatives.
- Parent traversal defines order. No sequence or cached depth survives the graph
  migration. Siblings are displayed by creation time and identifier.
- A conversation stores a nullable selected leaf. Normal reads return only its
  ancestry; graph inspection is a separate operation. Selection and append use the
  expected selected leaf as a compare-and-swap guard.
- A completed-response retry creates an attempt for the same parent user node. A
  successful retry adds and selects a persona sibling. Failed or interrupted
  attempts add no message, change no selection, and consume no retry allowance.
- One initial response plus three successful retries allows four persona siblings.
  The repository rechecks that bound when reserving and completing an attempt.
  Incomplete-turn continuation remains a different operation.
- Selecting an alternative selects that exact persona node. Restoring an existing
  future requires its exact saved leaf; the application never guesses descendants.
- Branching accepts an older persona node on the selected path, selects it under
  the compare-and-swap guard, and lets the next send create a new user child. It
  never deletes the old future, attempts, provenance, or summaries.
- Every persona node copies immutable response provenance: effective provider,
  model, generation configuration and budget, fixed Stage 5 response style,
  persona-evolution strategy name/version, and completing attempt identifier.
- Summaries are immutable branch-addressable lineages. A revision records its
  predecessor and persona checkpoint. At read time, use the deepest compatible
  checkpoint on the selected ancestry; never activate/deactivate revisions across
  the whole conversation.
- Ongoing branches in place. A latest Storyline scene and open Timeline day may
  branch in place. An older Storyline scene with later dependents and a closed
  Timeline day require a fork. Missing mode facts fail closed.

## Delivery rules

Keep values and repository contracts in Characters domain, orchestration and
policy in application, persistence in repositories, and widgets in UI. Require the
full ownership scope for every graph operation. Keep provider calls outside
transactions, preserve one-open-attempt and archive serialization, and recheck
selection, ownership, writability, and retry capacity on completion.

Each slice adds focused unit tests and cross-layer coverage where needed, then runs
its focused tests and `scripts/check.sh`. Persistence slices also run non-skipped
PostgreSQL migration and concurrency tests.

Use a new Characters migration and `alembic-characters.ini`; never edit applied
migrations. Test fresh and Stage 4-head upgrades beside populated Chat data, verify
`chat.alembic_version` and Chat objects are unchanged, and reject cross-schema SQL
offline. Downgrade is an explicitly destructive emergency escape hatch: test only
an immediately upgraded linear dataset and document that Stage 5 branches and
provenance are discarded.

## Slices

### 1. Freeze graph and branching contracts — Complete

Add immutable graph/path, alternative, retry, response-provenance, action, and
mode-policy values; typed invalid-parent, stale-selection, retry-limit, and
fork-required failures; separate selected-path and graph-inspection repository
reads; package exports; and architecture checks. Record the detailed semantics in
ADR 009. Unit tests cover ownership, roots, role alternation, cycles, parent-derived
order, immutability, all five action kinds, and Ongoing/Storyline/Timeline policy.

Complete when the contracts are executable without persistence or UI.

### 2. Persist the graph without changing the Stage 4 workflow

Migrate messages to parent links, conversations to a selected leaf, persona nodes
to immutable provenance, and summaries to branch-addressable lineages. Backfill the
existing sequence into one exact chain, select its final node, preserve identifiers,
timestamps, attempts, and summaries, then remove linear constraints. Implement
selected-path, graph, sibling, append, guarded selection, reservation, and atomic
completion operations. Existing send/resume remains visually linear.

Complete when production data is a valid graph and Stage 4 behavior still passes.

### 3. Make context and summaries branch-correct

Build response and summary prompts only from the selected ancestry. Resolve the
deepest eligible summary checkpoint and create immutable successor lineages per
branch. Bind prompt preparation and reservation to the same expected leaf.

Complete when no sibling, abandoned descendant, or partial attempt can enter
context and summaries recover correctly after path switches.

### 4. Add bounded completed-response retries

Expose retry availability and stream a new attempt for the selected final persona
response using current settings. On success, create/select a sibling with exact
provenance. Enforce three successful retries under repository locking at both
reservation and completion; preserve allowance after failures or interruptions.

Complete when four persona alternatives are durable and a fifth cannot commit,
including under PostgreSQL races and archival.

### 5. Add Ongoing branch and exact-future selection

Select an exact persona alternative or saved descendant leaf, and branch from an
older selected-path persona node. Return a detached deterministic graph view with
alternatives, retry counts, selected state, and branchable points. Reject stale,
foreign, off-path, ambiguous, current-leaf, active-attempt, and archived actions.

Complete when divergent Ongoing futures survive restart and switching never
mutates prior nodes, attempts, summaries, or provenance.

### 6. Apply the mode policy seam

Authorize every retry/branch operation through the pure policy. Ongoing mutates in
place; future mode adapters receive either `in_place` or `fork_required` plus exact
source references. Add no Storyline scene or Timeline day persistence.

Complete when missing/contradictory facts fail closed before any graph mutation.

### 7. Ship Ongoing controls

Render the selected transcript and per-turn alternatives with retry counts and
provenance. Add distinct **Retry response**, **Select alternative**, and confirmed
**Branch from here** controls only when valid. Keep incomplete continuation
distinct, disable writes for archives/open attempts, scope widget state, and reload
on stale selection.

Complete when users can safely create, inspect, select, and revisit Ongoing futures.

### 8. Prove the milestone

Exercise summary creation, three retries, alternative selection, branching before a
checkpoint, contradictory futures, restart, incomplete recovery, archival, exact
prompts, and ownership failures. Run the full isolated migration chain beside Chat
and the complete quality suite; update the master plan and shipped documentation.

Complete when selected-path isolation, recovery, migration safety, and all Stage 5
master-plan criteria are demonstrated without placeholder future-mode persistence.

## Deferred

- Stage 6: Storylines, scenes, continuity-scoped memory, temporal eligibility, and
  real older-scene forks.
- Stage 7: relationship/persona effects and rebuilding derived state after branch
  changes or continuity forks.
- Stage 8: Timeline dates, closure, timezone/DST rules, real closed-day forks, and
  editable response style.
- Stage 9: broad observability, export/deletion, and extraction hardening.
- Rich graph visualization and branch naming remain future UX decisions.
