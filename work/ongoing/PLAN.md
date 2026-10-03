# Stage 5 Execution Plan — Characters retry and branching

Status: Proposed

Last updated: 2026-10-03

## Scope and starting point

Deliver [Stage 5 of the master plan](../../PLAN.md): Characters messages become
immutable nodes in a recoverable conversation graph, each conversation records one
selected leaf, completed persona responses can have at most three retry
alternatives, and users can branch from an earlier point without deleting either
future. Only the selected root-to-leaf path may enter context, rolling summaries,
or later derivation.

Stage 4 is complete. It supplies one Ongoing conversation per continuity, a linear
alternating message history, durable generation attempts, immutable effective
provider/model configuration, rolling summaries, and a usable Streamlit workflow.
Its schema already has message-to-conversation ownership, persona responses linked
to their user message, globally unique message sequence positions, one response per
user message, and one active summary per conversation. Those linear constraints
must be migrated rather than worked around.

Storyline and Timeline creation do not exist yet. Stage 5 therefore implements and
tests their branching decision contract without inventing placeholder scenes, days,
or forks. Stage 6 must connect older-scene decisions to a real Storyline fork, and
Stage 8 must connect closed-day decisions to a real Timeline fork. Until then such
requests fail closed with an explicit `fork_required` result; they must never fall
back to an in-place branch.

The master plan and accepted ADRs remain authoritative. Before implementation,
record the detailed graph, retry-counting, selection, and summary-lineage behavior
below in a concise Characters ADR or the Characters design section.

## Behavioral contract to record

- A conversation has an implicit root. A message has one optional parent in the
  same conversation and continuity; persisted root children are user messages.
  Roles alternate along every edge: user messages descend from persona messages,
  and persona messages descend from user messages. Siblings are alternatives; rows
  and parent links are immutable after insertion.
- `sequence` becomes path depth, not a conversation-wide ordinal. Siblings have the
  same depth. Existing Stage 4 rows are backfilled into one parent chain without
  changing identifiers, contents, timestamps, or generation-attempt links.
- A conversation stores one nullable selected leaf. Empty conversations have no
  leaf. A new user message, completed response, selected retry alternative, or
  accepted branch action advances or replaces that pointer atomically. Reads return
  the selected root-to-leaf path in depth order; graph/alternative inspection is a
  separate repository operation so unselected nodes cannot accidentally enter a
  prompt.
- Branch and alternative selection use an expected selected-leaf identifier as a
  compare-and-swap guard. A stale browser tab or competing action receives a typed
  conflict and cannot silently change the active path.
- **Retry persona response** applies only to the selected path's final completed
  persona response. It creates a new generation attempt for the same parent user
  message, never a duplicate user message. A successful completion creates a
  sibling persona node and selects it. Failed or interrupted attempts remain
  attempt evidence, create no message, do not change selection, and do not consume
  an alternative slot.
- The initial persona response plus at most three successful retries permits four
  persona siblings for one user message. The repository enforces this limit inside
  the same transaction that reserves a retry attempt. Retry availability is derived
  from durable completed siblings, not Streamlit state. Incomplete-turn continuation
  remains distinct and does not consume this allowance.
- **Select alternative** selects an exact existing persona node. Selecting a sibling
  itself makes that response the leaf; selecting one of its saved descendant leaves
  restores that exact future. The implementation must not guess among multiple
  descendant futures.
- **Branch from here** accepts the empty root or a persona message on the selected
  path. It changes the selected leaf to that point under the compare-and-swap guard;
  the next send creates a new user child. A user-message branch point is represented
  by persona-response alternatives and is not a second branch command. Moving the
  selection alone does not delete nodes, attempts, or summaries.
- A persona message stores its immutable response provenance directly: effective
  provider, model, generation configuration/budget, fixed Stage 5 response-style
  snapshot, strategy name/version, and completing generation-attempt identifier.
  The attempt ledger remains the source for streaming lifecycle and partial output.
  Stage 5 records the current fixed style; editable style controls remain Stage 8.
- A rolling summary is eligible only when its checkpoint message is an ancestor of
  the selected leaf and its summarized source path matches that checkpoint's unique
  ancestry. Switching paths never edits a prior summary. The resolver chooses the
  deepest eligible checkpoint and creates a new immutable lineage when no saved
  summary covers the selected path. Unselected alternatives and partial attempts
  never enter response or summary prompts.
- Ongoing always branches in place. The mode policy returns `in_place` for the
  latest Storyline scene and an open Timeline day, and `fork_required` for an older
  Storyline scene with dependent scenes or a closed Timeline day. A caller cannot
  override a fork-required decision. Storyline/Timeline persistence integration is
  deferred to their owning stages.

## Delivery and verification rules

Implement the slices in order. Every slice must leave the application runnable,
have focused automated acceptance criteria, and avoid relying on a later slice for
its claimed outcome.

For every slice:

- Put immutable values and repository protocols in Characters domain packages,
  orchestration and policy in Characters application services, SQLAlchemy access in
  Characters repositories, and widgets in Characters UI. Do not import Chat.
- Add focused tests under `tests/characters/` and cross-layer scenarios under
  `tests/integration/characters/`. Use fake providers for ordinary tests and
  application-service doubles for Streamlit tests.
- Require explicit identity, persona, continuity, and conversation ownership on
  every graph operation. Reject foreign parents, leaves, attempts, checkpoints, and
  alternatives with typed errors.
- Preserve archive serialization and the one-open-attempt rule. Provider calls stay
  outside database transactions; completion must recheck ownership, writability,
  retry capacity, and the expected branch state.
- Run the slice's focused tests and `scripts/check.sh`. A slice that changes
  persistence also runs its PostgreSQL migration and concurrency tests; skipped
  PostgreSQL cases do not count as verification.

For each persistence change, add a new revision under
`alembic/characters/versions/` and use `alembic-characters.ini`. Never edit an
applied migration. Verify fresh upgrade, upgrade from the Stage 4 head, downgrade,
and re-upgrade on disposable PostgreSQL. Compare representative Chat rows, schema
objects, and `chat.alembic_version` before and after, and reject cross-schema SQL in
offline migration output.

## Slice sequence

| Slice | Self-contained outcome | Depends on | Database impact |
|---|---|---|---|
| 1 | Freeze graph, retry, selection, provenance, and mode-policy contracts | Stage 4 | None |
| 2 | Persist and read a selected immutable message graph while preserving Stage 4 behavior | 1 | Message, conversation, attempt, and summary migration |
| 3 | Assemble and summarize only the selected path | 2 | Existing graph/summary operations only |
| 4 | Create and select bounded persona-response alternatives | 2–3 | Existing graph/attempt operations only |
| 5 | Branch Ongoing from an earlier persona point without deleting either future | 2–4 | Existing graph operations only |
| 6 | Enforce mode-specific in-place versus fork-required decisions | 1, 5 | None; future mode adapters use the contract |
| 7 | Expose retries, alternatives, provenance, and branch controls in Ongoing UI | 4–6 | Existing application operations only |
| 8 | Prove Stage 5 branch isolation, recovery, and migration safety | 1–7 | Verification only |

### Slice 1 — Domain graph and branching decisions

Status: Proposed

Add frozen domain values for message parents, selected paths, alternative groups,
response provenance, retry availability, branch requests/results, and typed stale
selection, invalid-parent, retry-limit, and fork-required failures. Extend the
repository protocol with deliberately separate selected-path and graph-inspection
reads. Define the mode-policy input so Storyline can report dependent later scenes
and Timeline can report a closed day without importing future persistence models.

Keep generation-attempt lifecycle separate from completed alternatives. Define
exactly which effective generation, style, and strategy fields are copied to a
persona node at completion. Update package-boundary exports and architecture rules.

Verification:

- Domain tests accept valid alternating trees from the implicit root and reject
  cross-scope parents, multiple root nodes in one selected path, role violations,
  invalid depths, and mutable values.
- Policy tests cover Ongoing, latest and older Storyline scenes, open and closed
  Timeline days, including the fail-closed result when required facts are absent.
- Contract tests distinguish initial generation, incomplete-turn continuation,
  completed-response retry, alternative selection, and branch-from-here.
- Architecture tests prove the contracts import no application, infrastructure,
  UI, Chat, or future Storyline/Timeline model.

Complete when the graph and mode decisions are unambiguous and executable in unit
tests without persistence or UI.

### Slice 2 — Graph persistence and Stage 4 compatibility

Status: Proposed

Add the Characters migration and repository implementation for generalized parent
links, path depth, the selected conversation leaf, and persona-message provenance.
Remove the global `(conversation_id, sequence)` and one-response-per-user
constraints; replace them with ownership, parent-role/depth, response-attempt, and
appropriate sibling/index constraints. Backfill each existing Stage 4 conversation
into its exact linear chain and point selection at its final message. Empty
conversations remain unselected. Backfill completed persona provenance from its
generation attempt plus the fixed style and baseline strategy version.

Make summary rows branch-addressable in the same migration. Preserve their
immutable checkpoint/source data, remove the assumption that one conversation-wide
active summary is valid for every future branch, and add indexes needed to resolve
eligible checkpoints by selected ancestry. Do not discard existing summaries.

Implement repository operations to load the selected path, inspect children and
persona siblings, compare-and-swap the selected leaf, append a child, reserve an
attempt against a specific user node, and atomically complete an attempt with
provenance. Adapt existing send/continue/stream code to these operations while
retaining the linear Stage 4 user experience; no retry or branch button ships yet.

Verification:

- Repository tests round-trip a multi-level tree and prove selected-path reads omit
  siblings while graph inspection can recover every node and attempt.
- Upgrade tests preserve all Stage 4 identifiers, content, timestamps, attempt
  links, selected history, summary checkpoints, and effective generation data.
- Fresh, upgrade, downgrade, and re-upgrade tests verify Characters constraints and
  leave the populated Chat schema and migration head unchanged.
- PostgreSQL tests reject cross-conversation parents/selections, wrong role/depth,
  duplicate attempt completion, stale selected-leaf updates, and completion after
  archive. Concurrent selection or append actions have one deterministic winner.
- Existing Stage 4 conversation, recovery, summary, UI, and acceptance tests pass
  with unchanged visible behavior.

Complete when production data has a valid immutable graph and selected leaf, but
ordinary send/resume still behaves like Stage 4.

### Slice 3 — Selected-path context and branch-correct summaries

Status: Proposed

Change context eligibility and rolling-summary resolution to consume only the
repository's selected path. Resolve the deepest saved summary whose checkpoint is
on that path; when branching before a checkpoint, fall back to an eligible ancestor
summary or create a new lineage from selected messages. Summary advancement records
the exact selected checkpoint/source path and never deactivates or rewrites a
summary belonging to another future.

Keep complete-turn budgeting semantics from Stage 4. A selected user leaf remains
an incomplete turn; siblings, descendants of an unselected sibling, failed output,
and abandoned attempts are excluded. Prepare the same selected-path snapshot and
expected leaf for attempt reservation so a selection race cannot send a prompt for
one path and persist it on another.

Verification:

- Unit tests build two branches with contradictory content and assert that response
  and summary prompts contain only the selected ancestry.
- Tests switch before, at, and after summary checkpoints and verify deepest-ancestor
  reuse, new-lineage creation, chronological rendering, and no stale-summary leak.
- Integration tests restart the service, change selection, force compression on
  both branches, and recover each branch's correct summary and recent tail.
- A PostgreSQL race between prompt preparation and selection change rejects the
  stale reservation without calling the provider or changing either path.
- Existing capacity, summary failure, incomplete-turn, and ownership guarantees
  remain intact.

Complete when selected-path isolation is the only route into provider context and
rolling summaries are recoverable and correct on every stored branch.

### Slice 4 — Bounded persona-response retries

Status: Proposed

Add application operations to inspect retry availability, begin a retry of the
selected terminal persona response, stream it through the existing gateway, and
complete it as a sibling of the original response. Retry uses current saved
provider/model settings for the new attempt and stores that attempt's immutable
effective generation, fixed response style, and strategy version on the resulting
persona message. On successful completion, select the new alternative.

Enforce three successful retries per user turn in both service policy and the
repository transaction. Recheck the expected selected leaf and sibling count at
reservation and completion. Failed/interrupted output stays separately recoverable
as attempt evidence but does not change the selected path or alternative count.
Do not route retry through incomplete-turn continuation.

Verification:

- Unit tests cover availability from zero through three retries, current settings
  versus immutable old provenance, and rejection when the selected leaf is not a
  completed persona response.
- Integration tests create four persona siblings for one user, select each one,
  and reject a fifth while retaining every response and attempt.
- Failure before output, partial failure, cancellation, restart, and stale-selection
  cases preserve the original selected response and retry allowance.
- PostgreSQL races at the final slot cannot exceed four completed siblings; an
  archive race cannot commit or select the retry.
- Captured fake-provider prompts prove an unselected alternative never influences
  its sibling retry.

Complete when a completed persona turn has up to three durable alternatives with
exact provenance and deterministic recovery, selection, and limits.

### Slice 5 — Ongoing branch-from-here and alternative selection

Status: Proposed

Add application operations to select an exact persona alternative or saved leaf and
to branch an active Ongoing conversation from the implicit root or any persona node
on the selected path.
Both operations require the expected selected leaf and apply the mode policy before
changing selection. The next send attaches to the newly selected point. Preserve
the abandoned future, its alternatives, attempts, provenance, and summaries.

Return a graph view sufficient for UI rendering: selected path, alternatives at
each user turn, whether each node is selected, branchable points, and retry counts.
Keep it detached from SQLAlchemy and deterministically ordered by creation time and
identifier. Archived continuities remain inspectable but cannot change selection,
retry, branch, or send.

Verification:

- Application tests branch from the root, middle, and current leaf; send a distinct
  future; switch between futures; and recover exact histories after restart.
- Selecting an alternative with descendants never guesses a descendant. Choosing
  the alternative itself truncates the selected path there; choosing an exact saved
  leaf restores that future. A later branch/send builds only under the chosen node.
- Tests reject user-node branch commands, foreign/off-path nodes, stale leaf guards,
  active attempts, unmatched user tails where the action is ambiguous, and archives.
- Repository/application integration tests prove no branch action updates or
  deletes an existing message, parent, attempt, summary, or provenance snapshot.
- Concurrent branch/select/send actions serialize to one selected future without
  orphaning a committed write.

Complete when Ongoing users can create and revisit divergent futures without
destructive history changes or cross-branch context.

### Slice 6 — Mode-specific branch policy seam

Status: Proposed

Integrate the pure branching policy into every retry and branch application entry
point. Ongoing returns an in-place authorization. Define adapter-facing results for
latest versus older Storyline scenes and open versus closed Timeline days. A
fork-required result contains the source continuity/conversation/message references
needed by the owning future workflow, but performs no persistence itself.

Do not add Storyline scene tables, Timeline day/timezone fields, synthetic
continuities, or generic copy-all repository methods. Stage 6 will implement the
Storyline fork transaction after scenes exist; Stage 8 will implement Timeline
closure and fork transactions with its clock and timezone rules.

Verification:

- Table-driven unit tests cover every mode/state decision and reject incomplete or
  contradictory facts.
- Application contract tests prove retry/branch invokes policy before any graph
  mutation and that `fork_required` leaves selection and attempts unchanged.
- Ongoing integration tests prove all valid actions remain in the same continuity.
- Architecture tests ensure the policy stays Characters-owned and has no dependency
  on future infrastructure or Chat.

Complete when current Ongoing behavior is authorized through the same fail-closed
contract that later Storyline and Timeline workflows must obey.

### Slice 7 — Ongoing retry and branch UI

Status: Proposed

Render the selected path by default and expose alternatives at their persona turn.
Show the initial response plus used/remaining retry count, immutable provider/model,
strategy version, fixed response-style summary, and generation details. Add
**Retry response**, **Select alternative**, and **Branch from here** controls only
when their application preconditions hold. Require a clear branch confirmation
because changing selection alters subsequent context, but never imply that the old
future will be deleted.

Keep incomplete-turn continuation visually distinct from completed-response retry.
Disable graph mutations during an active attempt and for archives. Use scoped
widget keys so reruns, continuity switches, and area switches cannot replay an
action or show another continuity's alternatives. Surface stale-selection conflicts
by reloading the graph rather than retrying the mutation automatically.

Verification:

- Streamlit tests cover retry counts, four alternatives, selection, branch
  confirmation/cancel, retained old futures, provenance display, and reruns.
- Tests distinguish failed-turn continuation from completed-response retry and
  verify the appropriate control is shown for each state.
- Archived, active-attempt, unmatched-tail, retry-exhausted, and stale-browser states
  expose no invalid write path and present a useful explanation.
- Switching identities, continuities, or product areas clears graph-specific UI
  state and never calls a service with stale ownership.
- UI architecture tests continue to reject repositories, SQLAlchemy, provider SDKs,
  and Chat imports.

Complete when Ongoing branching and alternatives are usable and their limits,
selection, and provenance are visible without exposing persistence details.

### Slice 8 — Stage 5 acceptance and regression proof

Status: Proposed

Add one milestone scenario that starts an Ongoing continuity, creates enough turns
to summarize, retries one persona response three times, selects an alternative,
branches from before the summary checkpoint, creates a contradictory future,
switches between both futures after service restart, and verifies the exact prompt,
summary, provenance, and graph each time. Include incomplete generation recovery,
archival, and negative ownership cases.

Exercise the complete Characters migration chain on disposable PostgreSQL beside a
populated Chat schema. Document branch/retry behavior and the explicit handoff of
Storyline/Timeline fork persistence to Stages 6 and 8. Update the master plan only
after every Stage 5 completion criterion is demonstrated.

Verification:

- The milestone proves prior paths remain recoverable and no unselected response,
  descendant, summary, partial output, or foreign record enters current context.
- Repository and application suites cover branch selection, retry limits,
  compare-and-swap conflicts, archive serialization, and immutable provenance.
- Migration tests prove Stage 4 data survives graph backfill and that Chat objects,
  rows, and migration version remain unchanged.
- Characters tests run without importing or initializing Chat. Existing Chat,
  shell-routing, architecture, and Stage 4 regression tests remain green.
- `scripts/check.sh` and the non-skipped PostgreSQL migration/concurrency suite pass;
  a mocked Ollama contract test confirms retries use the existing provider seam.

Complete when the master Stage 5 criteria are met for the implemented Ongoing
workflow, the future mode rules fail closed through a tested contract, and no later
stage behavior has been simulated with placeholder persistence.

## Deferred scope

- Stage 6 owns Storyline creation, ordered scenes, actual older-scene continuity
  forks, branch-scoped extracted memory, temporal eligibility, and memory controls.
- Stage 7 owns relationship/persona proposals, events, projections, correction, and
  rebuilding derived state after selection or continuity forks. Stage 5 only
  guarantees that these consumers can request the selected path.
- Stage 8 owns Timeline creation, local dates, closure, timezone/DST behavior,
  actual closed-day forks, and user-editable response-style controls. Stage 5 stores
  the fixed effective style needed for provenance compatibility.
- Stage 9 owns broad observability, export/deletion, and extraction hardening beyond
  the focused isolation and migration proof required here.
- Branch visualization beyond a selected transcript with per-turn alternatives and
  branch controls remains a later UX decision. Branch naming is not introduced.
