# Stage 6 Execution Plan — Storylines and continuity-scoped memory

Status: In progress

Last updated: 2026-10-26

## Outcome

Add named Storyline continuities made of chronologically ordered scenes and add
long-term Characters memory for Storyline only. Each scene owns an independent
conversation graph, setup, title, and fixed Stage 6 response-style snapshot.
Only selected, temporally eligible memory from the same continuity may enter a
prompt. Users can inspect and manage memory, and branching an older scene with
later dependents creates a separate Storyline under a distinct duplicated profile
pair without changing the original. A profile pair owns only one active Storyline
at a time, and scenes are appended only when the latest has a complete
exchange. Archival permits a fresh independent Storyline for the same pair.
Memory extraction is context-aware: it interprets each new complete turn against
the selected scene history and current eligible memory, then proposes a bounded
delta instead of blindly emitting an unrelated set of facts.

Stage 6 builds on the immutable graph, exact-path selection, retry allowance,
branch-addressable summaries, generation provenance, and fail-closed mode policy
delivered in Stage 5. Ongoing remains one conversation with rolling summaries
and no extracted long-term memory. Timeline, relationship evolution, persona
adaptation, and editable response-style controls remain deferred.

## Proposed delivery contract

- A Storyline is a Characters continuity and therefore has one immutable identity,
  persona, mode, starting relationship, lifecycle, and memory boundary. An
  identity/persona pair may own at most one active Storyline. Archival retains its
  history and memory read-only but releases the pair for a fresh Storyline with an
  independent starting relationship and memory boundary. The same pair may
  independently own an Ongoing continuity.
- A Storyline has a user-authored name and starts with one scene. A scene has its own
  stable identifier, chronological position, title, setup, fixed response-style
  snapshot, conversation graph, and branch-addressable summary lineage.
- Scene order is append-only narrative chronology. The latest scene is the only
  normally writable scene. A next scene may be appended only after the latest has
  a complete selected exchange and has no unmatched input or open attempt. Scenes
  cannot be pre-created, inserted, reordered, or deleted, so at most the latest is
  empty. Scene setup freezes with its first user message. A title remains editable
  presentation metadata and never enters prompts.
- Storyline start uses the reviewed profile revisions and relationship selection
  already required for Ongoing. It atomically freezes newly used profiles, creates
  the named continuity and initial scene, and is idempotent by confirmation
  identifier. Ongoing availability and archived Storylines do not block a start,
  but an existing active Storyline for the pair does.
- The latest scene uses Stage 5 retry, alternative-selection, and in-place branch
  behavior. Branching from any persona message in an older scene that has a later
  dependent scene requires an explicit Storyline fork; retry and selection do not.
  The reviewed fork exactly duplicates at least one
  source profile to form a distinct pair with no Storyline, then copies the
  selected histories and scene metadata through the chosen source point into a
  new continuity with new owned identifiers. It leaves the source untouched and
  copies no later scene or unselected alternative. Eligible memory backed by
  copied evidence becomes an independent remapped lineage; no mutable or
  continuity-owned row is shared.
- A Storyline memory is a logical fact with a stable identifier and immutable
  revision lineage. The current revision is active or excluded; correction
  supersedes the prior revision, reactivation creates a new active revision, and
  hard deletion removes the complete lineage and provenance. There is no retained
  deleted tombstone.
- Every extracted revision and reinforcement evidence link identifies its source
  scene, complete selected turn, source persona checkpoint, occurrence position,
  learned position, extraction configuration, and creation time. Corrections
  retain the logical memory's source and temporal provenance while clearly
  recording user authorship.
- Eligibility is computed at read time. A memory must belong to the requested
  continuity, have an active current revision, have source provenance compatible
  with the selected branch, and have both occurrence and learned positions no
  later than the scene being assembled. Switching away from a source branch makes
  its derived memory ineligible without deleting it; switching back restores
  eligibility. A correction or exclusion affects the next assembled prompt.
- Extraction runs only after a persona response commits a complete selected turn.
  It is idempotent per source persona message, bounded, and outside the response
  completion transaction. Failure never rolls back the visible turn or permits
  partial output to become memory; a later explicit or automatic retry may finish
  the same extraction effect without duplicating revisions.
- The extractor receives an immutable, budgeted context snapshot containing the
  identity and persona labels needed for reference resolution, starting
  relationship, scene setup, compatible summary, a recent selected-path window,
  current branch- and time-eligible memories, and the exact source turn clearly
  marked as new evidence. Context may disambiguate or reconcile the source, but a
  new memory assertion must be supported or clearly confirmed by that source turn.
- Extraction returns a structured delta, not a bag of key/value candidates. A
  delta may create a logical memory, reinforce an unchanged memory with another
  evidence link, supersede an extracted revision, flag a conflict for later
  inspection without changing active memory, or make no change. Every non-empty
  operation references exact source evidence and, when applicable, an opaque
  identifier from the supplied current-memory snapshot.
- Application rules validate and apply deltas atomically. The model cannot mutate
  an excluded memory, supersede a user-corrected revision, target an omitted or
  foreign memory, invent identifiers, or apply multiple contradictory operations
  to one lineage. Ambiguous contradictions become recorded conflicts rather than
  silently replacing current memory.
- Context selection and delta extraction are separate, versioned Characters-owned
  strategy contracts. Stage 6 uses deterministic whole-record selection within a
  dedicated extraction budget and one contextual model call. Later implementations
  may add relevance ranking, confidence/salience, typed memories, or a separate
  claim-consolidation pass without changing memory ownership or provenance.
- Storyline context preserves the accepted Characters order: persona core,
  identity, relationship intent and starting state, eligible continuity memory,
  scene setup, fixed response style, then the compatible scene summary and recent
  selected-path messages. Eligibility, budgeting, summarization, extraction, and
  provider invocation remain separate responsibilities.
- Memory crosses a continuity only through the reviewed fork and copied evidence
  rules above; it never enters Ongoing or Chat. No Stage 6 table, query, prompt,
  service, migration, or UI operation may import or inspect Chat.

Slice 1 records these details in ADRs 025, 031, and 032 and verifies them against
ADRs 006, 008, 009, and 013 before persistence work begins. If an accepted
decision changes, revise or supersede it rather than silently implementing a
different rule.

## Delivery and verification rules

Implement the slices in order. Each slice must leave Chat and Characters runnable
and must not rely on a later slice to satisfy its own acceptance criteria. Domain
values and repository protocols remain in Characters domain, orchestration and
policy in application services, SQLAlchemy access in database repositories,
provider access in infrastructure, prompts in `characters/prompts/`, and widgets
in Characters UI.

Every implementation slice adds focused unit coverage in the matching
`tests/characters/` layer and integration coverage when it crosses service and
repository boundaries. Extend architecture tests whenever ownership or import
boundaries change. Tests use fake providers unless a separately enabled smoke test
is explicitly being run.

Persistence slices add forward-only revisions under
`alembic/characters/versions/` and use `alembic-characters.ini`. Never edit an
applied migration. Verify fresh upgrade, upgrade from the Stage 5 head, downgrade
to the preceding head where loss is understood, and re-upgrade on disposable
PostgreSQL. Compare Chat schema objects, representative Chat rows, and
`chat.alembic_version` before and after; render offline SQL and reject any
cross-schema reference. PostgreSQL race and constraint cases must actually run
rather than count as skipped verification.

For each slice, run the smallest relevant tests while developing. At milestone
verification, run the CI-equivalent commands independently:

```bash
timeout 30s uv run black --check src tests
uv run isort --check-only src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -v
```

If Black times out, do not retry it during that run; continue the other checks and
record the timeout. Fix ordinary formatting failures and rerun Black once with the
same cap.

## Slice sequence

| Slice | Self-contained outcome | Depends on | Database impact |
|---|---|---|---|
| 1 | Record the complete Storyline and memory decisions | Stage 5 | None |
| 2 | Add executable Storyline and scene contracts | 1 | None |
| 3 | Add executable memory and contextual-delta contracts | 1 | None |
| 4 | Persist named Storylines and ordered scene ownership | 2 | Storyline and scene migration |
| 5 | Start, resume, append the next scene, and archive Storylines | 4 | Existing Storyline operations only |
| 6 | Converse and summarize within one scene | 4–5 | Existing conversation and summary operations |
| 7 | Branch latest scenes and structurally fork older scenes | 4–6 | Fork provenance in the Storyline migration |
| 8 | Persist memory lineages, evidence, effects, and conflicts | 3–4 | Memory migration |
| 9 | Manage memory lifecycle and unresolved conflicts | 8 | Existing memory operations only |
| 10 | Build branch-aware extraction context snapshots | 3, 6, 8 | Existing repository operations only |
| 11 | Preserve eligible memory when a Storyline forks | 7–10 | Existing memory operations only |
| 12 | Produce contextual delta proposals through a provider | 3, 10 | None |
| 13 | Validate and atomically apply extraction deltas | 8, 10, 12 | Existing memory operations only |
| 14 | Add eligible memory to Storyline response context | 6, 8–10, 13 | Existing repository operations only |
| 15 | Ship Storyline creation, navigation, and scene management UI | 5 | Existing repository operations only |
| 16 | Ship Storyline conversation, retry, and fork UI | 6–7, 11, 14–15 | Existing repository operations only |
| 17 | Ship continuity-scoped memory and conflict controls | 9, 13–16 | Existing repository operations only |
| 18 | Update project documents for shipped Stage 6 behavior | 1–17 | None |
| 19 | Prove the Stage 6 milestone and area isolation | 1–18 | Verification only |

The split deliberately keeps four kinds of risk out of the same slice: schema
shape, application policy, provider interpretation, and Streamlit state. Memory
persistence can therefore be reviewed before provider output is trusted; snapshot
selection can be proven without a model; provider parsing has no write authority;
and reconciliation is tested before memory reaches response prompts or UI. The two
fork slices similarly separate graph copying from later memory remapping.

### Slice 1 — Record the Storyline and memory decisions

Status: Complete

Record the durable choices above in focused Characters ADRs and reconcile the
relevant `DESIGN.md` rules in the same change. In particular, settle initial-scene
creation, active-pair uniqueness and replacement after archive, append eligibility,
fork copy/remapping
behavior, logical memory revision state, the meaning of occurrence and learned
positions, correction provenance, extraction idempotency, and whether deletion of
source records is allowed while memory provenance exists. Split scene lifecycle,
memory lifecycle, and contextual extraction into focused ADRs. Also fix extraction
snapshot blocks, dedicated budget behavior, delta vocabulary, evidence rules,
application-side conflicts, and strategy provenance. Do not borrow Chat ADRs
017–020 as Characters contracts.

Verification:

- ADR and design text agree with ADRs 006, 008, 009, and 013 and contain no Stage 7
  relationship/persona evolution or Stage 8 Timeline/style behavior.
- The decisions define every state transition, temporal comparison, fork-copy
  rule, delta operation, protected-memory rule, and extension seam used by later
  slices without prescribing repository or provider mechanics.
- Run `git diff --check -- DESIGN.md docs/decisions/` and verify relative links.

Complete when later slices can implement the feature without inventing durable
behavior in repositories, provider adapters, or UI.

### Slice 2 — Add executable Storyline and scene contracts

Status: Complete

Add immutable Storyline, scene, append-eligibility, fork-source, and mode-action
values with complete validation and package exports. Extend the fail-closed mode
policy so real Storyline facts produce `in_place` or `fork_required` without
persistence guesses. Define repository protocols at the owning package boundary
and typed failures for an active Storyline conflict, stale Storyline revisions,
locked setup, an incomplete latest scene, invalid scene ownership, stale selected
leaves, and fork conflicts. Add no SQLAlchemy models or services.

Verification:

- Unit tests cover field bounds, immutability, active-pair uniqueness, archived
  replacement, immutable append order, next-scene eligibility, setup locking, fork
  inputs, and every Storyline branch-policy outcome.
- Protocol and architecture tests prove the contracts import neither application,
  infrastructure, UI, nor Chat.

Complete when persistence and application slices can depend on one executable
Storyline vocabulary without duplicating invariants.

### Slice 3 — Add executable contextual-memory contracts

Status: Complete

Add immutable logical-memory, revision, evidence, temporal-position,
extraction-context, selection-result, delta-operation, extraction-effect, conflict,
and management-command values with complete validation and package exports. Define
versioned context-selector and delta-extractor strategy protocols separately from
provider adapters. Define repository protocols and typed failures for invalid
delta targets, stale lifecycle operations, protected corrections, conflicts, and
temporal provenance. Add no persistence or provider implementation.

Verification:

- Unit tests cover current-revision lifecycle, occurrence/learned comparisons,
  extraction snapshot ownership, operation bounds, create/reinforce/supersede/
  conflict/no-change validation, contradictory deltas, and protected user
  corrections.
- Protocol tests prove selectors and extractors are substitutable and keep
  provider types out of domain contracts.
- Architecture tests prove the memory domain imports neither Chat nor outward
  Characters layers.

Complete when storage, selection, provider, and reconciliation slices can evolve
independently behind stable domain contracts.

### Slice 4 — Persist named Storylines and ordered scenes

Status: Complete

Generalize continuity persistence so Ongoing retains its sole conversation while
a Storyline owns multiple scene conversations. Add Storyline metadata, optimistic
revision, active profile-pair ownership, scene metadata and immutable ordinal,
fixed Stage 6 style, and optional fork provenance. Create every scene conversation
with the same full identity/persona/continuity ownership used by Stage 5 graphs.
Keep Ongoing rows and behavior unchanged and continue rejecting Timeline creation.

Implement Characters-owned repository protocols and `Db` implementations for
owned Storyline and scene reads, deterministic listing, guarded metadata changes,
eligible next-scene append, setup locking, and atomic initial creation. Enforce one
active Storyline per identity/persona pair, unique immutable scene positions,
cross-row ownership, latest-scene append rules, and mode/lifecycle constraints in
PostgreSQL as well as application preflight.

Verification:

- Repository tests round-trip every Storyline and scene field and reject foreign
  continuity, wrong mode, active-pair conflicts, duplicate order, ineligible append,
  stale revision, archived writes, and cross-owner conversation references.
- PostgreSQL concurrency tests show one active start per pair, permit a start after
  archive, and let one eligible append win at a revision while first interaction
  serializes with setup locking.
- Migration tests preserve all Stage 5 Ongoing graphs, attempts, summaries, and
  provenance while creating no Chat object or cross-schema reference.

Complete when named Storyline/scene ownership is durable and Ongoing still passes
its existing repository and migration suite without UI changes.

### Slice 5 — Add the Storyline lifecycle service

Status: Complete

Add reviewed Storyline start, initial-scene definition, latest-scene resume,
deterministic identity/persona grouping, metadata editing, guarded next-scene
append, and permanent archive operations. Reuse the existing relationship default
resolution and transactional profile-freezing rules through mode-neutral
application helpers rather than duplicating Ongoing logic. Make confirmation
idempotency include all Storyline start fields.

Expose mode-specific start availability: an active Ongoing blocks only another
Ongoing, while only an active Storyline blocks another Storyline for that pair.
Offer resume-latest or append-next only when their guards allow it. Archive remains
idempotent, makes all scenes and memory read-only, releases the pair for a fresh
independent Storyline, and never unfreezes either profile.

Verification:

- Service and integration tests cover reviewed starts, stale profiles, duplicate
  submissions, conflicting confirmation reuse, active-pair uniqueness, fresh start
  after archive without history or memory transfer, latest resume,
  empty/incomplete-scene append rejection, metadata changes, and archives.
- PostgreSQL races prove starts freeze profiles atomically and competing next-scene
  appends cannot create multiple empty scenes or violate order.
- Ongoing start availability and lifecycle tests remain unchanged.

Complete when Storylines can be managed entirely through application services
without direct UI or service-level SQLAlchemy access.

### Slice 6 — Converse and summarize inside scenes

Status: Complete

Make conversation orchestration accept a mode-owned conversation target and add a
Storyline adapter that validates the scene, lifecycle, selected leaf, setup lock,
and latest/older-scene action policy before reserving work. Reuse the Stage 5 graph,
attempt, retry, exact-future selection, provenance, and branch-addressable summary
mechanisms. Keep provider calls outside transactions and make the first committed
user input atomically lock scene setup. Only the latest scene accepts normal writes.

Add a Storyline prompt and context eligibility/budgeting path with no memory input
yet. It includes the scene setup and fixed Stage 6 style, uses only the scene's
compatible summary and selected ancestry, and cannot read another scene transcript
as short-term context. Summary generation remains scene/conversation scoped.

Verification:

- Prompt tests assert exact block order and prove titles, other scenes, unselected
  alternatives, partial attempts, and future memory placeholders are absent.
- Cross-layer tests cover first send, continuation, failure recovery, retries,
  alternative selection, summary checkpoints, restart, archival, and ownership.
- Existing Ongoing prompt bytes and behavior remain stable except for deliberate
  mode-neutral refactoring covered by regression tests.

Complete when an active scene supports the full Stage 5 conversation lifecycle
with isolated context and summaries.

### Slice 7 — Structurally fork Storylines from older scenes

Status: Complete

Connect actual Storyline persistence to the Stage 5 branch-policy seam. Keep retry,
alternative selection, and branching in place for the latest scene. When Branch
from here names any persona message in a scene with later dependents, return a
reviewed fork preview. Retry and alternative selection never fork. The user confirms an
exact authored duplicate of at least one source profile, producing a distinct
identity/persona pair with no Storyline; then atomically create the fork at the
expected source leaf and Storyline revision. The fork uses a new user-authored
name, retains the source starting relationship, and freezes newly duplicated
profiles in that transaction.

Copy earlier selected scene histories and the chosen scene's exact ancestry through
the persona branch point, assigning new continuity-owned identifiers and retaining
explicit source-to-copy provenance. Remap attempts, persona-message provenance,
and compatible summary checkpoints only where the accepted contract requires them.
Do not copy later scenes, unselected siblings, or open attempts. Persist a complete
identifier mapping that Slice 11 can use when memory is introduced. After the fork
commits, make the copied branch point the selected leaf only in the new Storyline;
leave every source record byte-for-byte unchanged.

Verification:

- Unit and integration tests distinguish latest-scene in-place actions from
  older-scene forks and reject stale, archived, foreign, contradictory, revised
  duplicate profiles, occupied target pairs, or incomplete sources before writes.
- Fork tests compare exact copied paths and remapped provenance, prove the original
  selected leaves and futures remain unchanged, and resume both Storylines under
  their distinct pairs after restart.
- PostgreSQL races permit at most one idempotent fork per request and prevent a
  source change from producing a mixed snapshot.

Complete when every real Storyline policy outcome is executable and older-scene
changes preserve both futures without shared ownership.

### Slice 8 — Persist memory lineages and extraction records

Status: Complete

Add SQLAlchemy models and a Characters migration for logical memories, immutable
revisions, supporting evidence, extraction effects, and unresolved conflicts.
Implement repository primitives to read owned lineages and effects, reserve one
effect per source persona message, attach unique evidence, atomically persist an
already validated delta, and hard-delete a complete lineage with dependent
evidence/conflicts. Do not add management services, provider calls, prompt
eligibility, or fork copying.

Enforce one current revision per logical memory, unique evidence per
memory/source turn, immutable provenance, monotonic revisions, effect idempotency,
and full identity/persona/continuity ownership. Persist selector, extractor,
prompt-schema, provider, model, effective configuration, source checkpoint, and
terminal outcome fields needed by later slices. Use bounded string columns aligned
with domain validation and concise `doc` descriptions on every field.

Verification:

- Repository tests round-trip each record independently and reject foreign owners,
  stale targets, duplicate evidence, conflicting current revisions, and invalid
  effect transitions.
- PostgreSQL races prove one effect reservation and one current revision win.
- Migration tests cover fresh upgrade, upgrade from the preceding Storyline head,
  the full Stage 5-to-current chain, downgrade/re-upgrade, and Characters-only
  schema ownership beside unchanged Chat data.

Complete when later application slices have safe persistence primitives without
exposing memory to prompts or users.

### Slice 9 — Add memory and conflict management workflows

Status: Pending

Add application services to list and inspect continuity-owned memory, correct an
active revision, exclude, reactivate, hard-delete, inspect conflicts, and dismiss a
conflict under expected revisions. Corrections preserve logical source/temporal
provenance while recording user authorship. Hard deletion removes the complete
lineage, evidence, and associated conflicts. No extraction is triggered here.

Repositories repeat decisive stale, lifecycle, ownership, and protected-revision
guards transactionally. Operations are idempotent only where the contract says so;
stale commands cannot silently act on a newer revision.

Verification:

- Service/repository tests cover every legal transition and reject correction of
  excluded memory, foreign ownership, stale revisions, repeated deletion, and
  conflict actions against changed memory.
- PostgreSQL concurrency tests serialize correction, exclusion/reactivation,
  deletion, and conflict dismissal.
- Tests prove management operations do not invoke providers or query Chat.

Complete when memory and conflicts are fully controllable through application
services but remain absent from extraction and response prompts.

### Slice 10 — Build contextual extraction snapshots

Status: Pending

Implement the shared pure branch/temporal eligibility service and the baseline
extraction context-selector strategy. For one still-selected complete turn, build
an immutable snapshot from owned identity/persona labels, starting relationship,
scene setup, compatible summary, recent selected ancestry, current active eligible
memories, and the exact source turn marked as mandatory new evidence.

Use a dedicated extraction-token budget. Select whole records deterministically,
retain the source turn, and report included and omitted identifiers, checkpoints,
token counts, and selector version. Context can later support interpretation but
this slice performs no provider call or persistence mutation.

Verification:

- Pure matrix tests cover same/earlier/later scenes, learned-later facts, selected,
  deselected and reselected branches, excluded/corrected/deleted memories, and
  foreign continuities.
- Snapshot tests assert exact block order, deterministic whole-record omission,
  mandatory source retention, capacity failure, and empty optional context.
- Tests prove Ongoing and Chat cannot request a Storyline extraction snapshot.

Complete when a provider-independent, reproducible snapshot defines exactly what
the future extractor may see.

### Slice 11 — Preserve eligible memory across Storyline forks

Status: Pending

Extend the Slice 7 fork transaction using its persisted identifier mapping. Copy
only active memory lineages whose originating evidence is present on the copied
selected histories. Remap scene/message provenance, copy only supporting evidence
whose source is also present, assign new continuity-owned identifiers, and retain
revision authorship. Do not copy excluded memory, unresolved conflicts, unfinished
effects, omitted scenes, or unselected evidence. Share no mutable or
continuity-owned row.

Keep structural fork behavior unchanged when no memory exists. Fail atomically if
source selection, memory revision, or Storyline revision changes during the copy.

Verification:

- Integration tests compare exact source-to-fork mappings and eligible copied
  lineages, including corrections and reinforcements.
- Negative cases prove excluded/conflicted/future/unselected memory remains absent
  and source rows remain byte-for-byte unchanged.
- PostgreSQL races prevent mixed snapshots and keep repeated fork requests
  idempotent.

Complete when a fork retains only knowledge supported by its copied evidence and
both continuities evolve independently afterward.

### Slice 12 — Produce contextual delta proposals

Status: Pending

Add the configured Characters memory-extraction capability, strict prompt/schema,
parser, and provider adapter. Given only a Slice 10 snapshot, return a bounded
proposal containing `create`, `reinforce`, `supersede`, `conflict`, or no-change
operations with exact source-turn evidence and opaque supplied memory identifiers.
Resolve the utility provider/model/configuration independently from visible
response generation. Do not write memory or reserve extraction effects.

The prompt states that prior context may resolve references, duplication, or
change, but facts found only in older context cannot become new source claims.
Normalize syntax at the adapter boundary while leaving lifecycle authorization and
semantic reconciliation to Slice 13.

Verification:

- Parser/contract tests cover every operation plus malformed JSON, extra fields,
  invalid types, oversized results, unknown operation kinds, and missing evidence.
- Prompt tests assert exact snapshot rendering and explicit source/context
  separation.
- An optional provider smoke test is separately gated; ordinary tests use a fake
  adapter and require no Ollama or network access.

Complete when a provider can propose a typed delta but has no authority to mutate
memory.

### Slice 13 — Validate and apply contextual deltas

Status: Pending

Add the post-completion extraction orchestrator. Confirm the source persona message
is still selected and eligible, reserve its idempotent effect, request a Slice 10
snapshot, invoke the Slice 12 extractor, validate the complete proposal against
current persisted state, and atomically apply the delta with its terminal receipt.

Creates cannot collide with an existing logical subject; reinforces attach evidence
without a duplicate revision; supersedes target only a supplied active extracted
revision; conflicts preserve current memory. Reject invented or omitted targets,
duplicate targets, contradictory operations, unsupported evidence, protected user
corrections, excluded memory, and over-limit results. Any invalid operation rejects
the whole delta. Retryable failure cannot roll back the visible response or
duplicate a completed effect.

Verification:

- Tests prove unmatched input, incomplete attempts, unselected siblings, Ongoing,
  archives, and foreign scenes never invoke extraction.
- Application/repository tests cover no-change, create, reinforce, supersede, and
  conflict plus mixed valid/invalid deltas and concurrent lifecycle changes.
- Integration tests prove contextual disambiguation/deduplication and that facts
  present only in prior context are not re-created from the new turn.
- PostgreSQL races prove one terminal effect and no partial delta writes.

Complete when each eligible turn yields at most one auditable atomic delta and
extraction failure cannot damage conversation completion.

### Slice 14 — Add memory to Storyline response context

Status: Pending

Apply Slice 10's eligibility semantics to response context through a
continuity-scoped repository query and a separate response-memory selector/budget.
Insert whole eligible memories at the accepted Characters context position while
preserving mandatory persona, identity, relationship, scene, style, compatible
summary, latest complete turn, and current input. Never truncate a memory or let
optional memory displace mandatory context.

Corrections, exclusions, reactivations, deletions, branch switches, and conflict
creation affect the next prompt without rewriting prior generation provenance.
Keep response selection independently versioned so extraction-selection changes do
not silently change visible prompts.

Verification:

- Eligibility parity tests prove extraction and response selectors share temporal
  and branch rules while retaining separate ordering and budgets.
- Budget tests cover deterministic omission, exact token accounting, mandatory
  blocks, and capacity failure.
- Exact-prompt integration tests prove future, unselected, conflicted, Ongoing,
  foreign-continuity, and Chat memory never appears.

Complete when each Storyline response sees exactly the eligible memory that fits.

### Slice 15 — Ship Storyline creation and scene-management UI

Status: Pending

Add dedicated **Storylines** and **New Storyline** routes. Extend identity → persona
navigation with the pair's sole active Storyline and clearly separated archived
Storylines while keeping Ongoing distinct. Provide the reviewed relationship/start
flow when the pair has no active Storyline, initial-scene definition,
resume/archive actions, and guarded **Next scene**, title, and setup controls.
Expose no pre-creation, insertion, or reorder action. Do not expose chat, fork, or
memory controls yet.

Scope Streamlit state by complete ownership, invalidate stale reviews and forms,
and prevent reruns from replaying starts or scene mutations.

Verification:

- Streamlit tests cover start review, duplicate submission, active-pair conflicts,
  replacement after archive, navigation, resume-last versus next-scene choices,
  append eligibility, stale revisions, archives, continuity switching, and action
  replay.
- Integration tests exercise the UI through real application services without
  repository or SQLAlchemy access from widgets.

Complete when users can create, organize, resume, and archive Storylines safely.

### Slice 16 — Ship Storyline conversation and fork UI

Status: Pending

Add selected-scene chat using the established conversation controls: streaming,
recovery, retries, alternatives, and exact-future selection. Expose Branch from
here for every persona message: branch in place in the latest scene and show a
reviewed, explicitly named fork preview for an older scene with dependents. Do not
offer retry or selection as fork operations. The preview clearly creates an exact
duplicate source profile and a distinct target pair. Navigate to the returned fork
without changing the source selection. Keep memory management out of this slice.

Disable writes for archived continuities and open attempts, reload stale selected
leaves, and prevent reruns from replaying generation, retry, selection, or fork
actions.

Verification:

- Streamlit tests cover generation recovery, alternatives, latest-scene branches,
  older-scene forks, stale previews, restart, archives, and action replay.
- Area-switching tests prove Storyline chat does not disturb Ongoing or initialize
  Chat.

Complete when every Stage 6 Storyline conversation and fork workflow is usable
without memory-management UI.

### Slice 17 — Ship memory and conflict controls

Status: Pending

Add a continuity-scoped memory view with current revision, source/evidence,
temporal, extraction-strategy, and lifecycle provenance. Allow correction,
exclusion, reactivation, and confirmed permanent deletion only through Slice 9
services. Show unresolved delta conflicts separately with new evidence and current
memory; allow dismissal, keeping the current value, or entering the normal
correction flow.

Scope widgets by full ownership, invalidate stale forms after revision/branch
changes, and clearly distinguish extracted, reinforced, corrected, excluded, and
conflicted state. No UI action may rerun extraction implicitly.

Verification:

- Streamlit tests cover provenance, correction and immediate prompt effect,
  exclusion/reactivation, reinforcement evidence, conflict inspection/dismissal,
  deletion confirmation, stale revisions, empty states, and continuity switching.
- Tests prove Ongoing exposes no extracted-memory controls and Characters controls
  never inspect Chat memory.

Complete when users can understand and control every durable Stage 6 memory effect.

### Slice 18 — Update project documents

Status: Pending

Update project documents only after shipped behavior and operator-facing names are
verified:

- Update `README.md` capabilities, Characters scope/context table, quick-start
  walkthrough, local/external data-flow explanation, and supported Characters
  memory-provider configuration. Remove the current limitation that Characters has
  no extracted long-term memory while stating that Ongoing still does not extract
  it and Storyline memory crosses continuities only through a reviewed fork with
  remapped copied evidence.
- Reconcile `DESIGN.md` with final Storyline, fork, temporal memory,
  contextual-delta extraction, conflict, lifecycle, and correction behavior;
  update its `Last updated` date and remove superseded statements.
- Mark Stage 6 complete in root `PLAN.md`, keep Stage 7 as the next delivery stage,
  and update `work/ongoing/TODO.md` without turning either into a release log.
- Keep the Stage 6 ADRs concise and verify every link, command, path, environment
  variable, default, model name, and claim against the repository.

Run `git diff --check -- README.md DESIGN.md PLAN.md work/ongoing/TODO.md` and
relevant documentation/link checks. Broader code checks remain Slice 19 work.

Complete when README describes only shipped behavior, DESIGN is coherent, and
delivery status remains in the plan files.

### Slice 19 — Prove the Stage 6 milestone

Status: Pending

Add a focused acceptance journey that creates one Storyline for a pair, archives
it, starts a fresh independent Storyline for that pair, and creates a simultaneous
fork only after exact profile duplication. Append scenes one at a time, reject a
second empty scene, generate and summarize selected branches,
creates/reinforces/supersedes/conflicts through contextual extraction, manages
memory, verifies past-scene as-of behavior, switches alternatives, forks an older
scene, restarts, and resumes both original and fork. Assert exact extraction
snapshots, deltas, and response prompts at branch and temporal boundaries.

Run the complete Characters migration chain on disposable PostgreSQL beside
populated Chat data, including concurrency cases, then run the full CI-equivalent
suite listed above. Inspect the final diff for forbidden cross-area imports,
queries, foreign keys, identifiers, prompts, and initialization paths. Record any
Black timeout or gated smoke test honestly in the handoff.

Complete when Storylines and memories are isolated, temporal and branch rules
hold, each pair owns at most one active Storyline, archived state never enters its
replacement, at most one latest scene is empty, corrections affect the next
context, older-scene futures survive under distinct fork pairs, Ongoing remains
memory-free, Chat is unchanged, and all checks pass.

## Deferred

- Stage 7 owns relationship events/projections, persona adaptation, proposal
  validation, evidence thresholds, hysteresis, and rebuilding those derived states
  after branch changes or Storyline forks.
- Stage 8 owns Timeline dates, timezone and DST rules, day closure, Timeline forks,
  and user-editable response-style controls. Stage 6 persists only the fixed style
  needed for immutable message provenance.
- Stage 9 owns broad observability, export/deletion hardening, and extraction-readiness
  proof beyond the focused diagnostics required here.
- Standalone memory transfer between continuities outside a reviewed Storyline
  fork, importing Chat memory, automatic Storyline naming/setup generation, rich
  graph visualization, branch naming, and merging forks are outside Stage 6.
- Embedding or learned relevance ranking, confidence/salience scoring, typed or
  graph memories, and a separate claim-extraction/consolidation pass are future
  strategy implementations behind the Stage 6 contracts, not baseline behavior.
