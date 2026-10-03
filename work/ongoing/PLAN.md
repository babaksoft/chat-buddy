# Stage 4 Execution Plan — Characters foundations and Ongoing mode

Status: In progress

Last updated: 2026-10-03

## Scope and starting point

Deliver [Stage 4 of the master plan](../../PLAN.md): an identity and persona can
start, resume, and converse within an isolated Ongoing continuity. Both profiles
allow authored edits before first use; starting a continuity freezes its identity
and persona transactionally. Each identity/persona pair has at most one active Ongoing continuity. Long conversations use a
continuity-owned rolling summary, with no extracted long-term memory.

Stages 0–3 are complete. At the start of Stage 4, Characters had empty domain,
application, and prompt packages, a landing page, independent database
configuration and metadata, and an empty Alembic baseline at `61a5c7060ad9`. It
had no profile, continuity, conversation, message, gateway, or summary implementation. Build on that scaffold
and the existing area-isolation checks. Existing Chat implementations are useful
behavioral references, but are not dependencies of Characters.

This document records implementation scope and verification. Slices 1–7 are
implemented; Stage 4 remains in progress and has not met milestone acceptance. The master plan and accepted
ADRs remain authoritative.

## ADR constraints

| Record | Stage 4 consequence |
|---|---|
| [006 — Continuity ownership](../../docs/decisions/006-continuity-ownership.md) | Continuity owns conversations, summaries, starting relationship state, and future adaptation. Every history/context operation requires continuity ownership. |
| [007 — Identity and persona first-use freezing](../../docs/decisions/007-identity-and-persona-immutability.md) | Allow authored identity/persona edits before first use; freeze both at first continuity creation. Never switch continuity ownership. After first use, authored changes require new or duplicated profiles. |
| [008 — Mode context and memory](../../docs/decisions/008-mode-context-and-memory.md) | Preserve Characters context ordering. Ongoing has no extracted memory; eligibility, budgeting, and summarization are separate responsibilities. |
| [009 — Branches and retries](../../docs/decisions/009-branches-and-retries.md) | Completed messages are immutable. Stage 4 has a sole conversation path; selected leaves, response alternatives, the three-retry allowance, and branch actions arrive in Stage 5. |
| [010 — Relationship evolution](../../docs/decisions/010-relationship-evolution.md) | Persist relationship intent and a qualitative starting state per continuity. An established state is user-selected and invents no shared events. Evolution arrives in Stage 7. |
| [011 — Timeline time and closure](../../docs/decisions/011-timeline-time-and-closure.md) | Reserve Timeline as a mode value, but defer dated conversations, timezone-boundary behavior, closure, and DST handling to Stage 8. |
| [012 — Legacy migration](../../docs/decisions/012-legacy-data-migration.md) | Superseded: do not import legacy rows, create archived default continuities, or transfer Chat memory. |
| [013 — Independent areas](../../docs/decisions/013-separate-chat-and-characters-areas.md) | Use Ongoing terminology, Characters-owned layers and schema, and the shared routing shell. No Chat imports, queries, foreign keys, services, prompts, or runtime initialization. |
| [014 — Provider-neutral access](../../docs/decisions/014-provider-neutral-llm-access.md) | Own Characters gateway contracts and adapters. Start with Ollama and prove substitution using a test provider. Cloud vendors require a Characters-applicable follow-up ADR. |

Use the [Characters sections of DESIGN.md](../../DESIGN.md#characters-area) for
identity attributes, persona layers, the navigation hierarchy, starting
relationship fields, and context order. Chat ADRs 015–022 do not automatically
define Characters behavior or authorize Characters cloud adapters.

## Proposed Stage 4 behavior

These choices fill Stage 4 implementation gaps without changing accepted ADRs.
Record them in Characters design documentation before implementing the affected
slice; add a concise behavioral Characters ADR where a new durable contract needs
one. Keep implementation details and verification in the master/stage plans.
Do not silently copy Chat lifecycle or context policy.

- Represent immutable domain values and application snapshots with frozen
  Pydantic models. An editable identity or persona is replaced by a validated value
  through an application service, not mutated in memory. Declare Pydantic directly with
  `uv add` if needed rather than relying on a transitive dependency.
- Create a Characters-owned default identity displayed as **You**, idempotently
  when Characters setup first needs it. Do not fabricate demographic details.
  Support name, optional gender, age or birth date, optional pronouns/preferred
  address, and an optional valid IANA timezone. Age and birth date are alternative
  inputs. Timezone is not required to start Ongoing.
- Allow revision-checked edits to all authored identity and persona fields before
  first continuity creation, then freeze all fields, including display fields.
  Persona freezing is global on first use with any identity. Duplication copies
  only authored fields, optionally revised, into an editable profile with a new
  identifier, revision 1, and no continuity history, relationship state, adaptation,
  or current state. Identity duplicates are non-default. Separate permanent freeze
  flags enforce edit eligibility; revision counters detect stale edits and starts
  without requiring historical authored revision storage.
- Start creates an active Ongoing continuity, its sole conversation, and its
  starting relationship snapshot in one transaction. The same transaction freezes
  both selected profiles after locking their rows in a consistent order and
  verifying both submitted revisions. Selection, draft starts, and canceled
  confirmation do not freeze either profile; failures roll back freezing and
  continuity creation together. A confirmation request identifier makes repeated
  submission idempotent; reuse with different submitted data is rejected.
- Offer all four relationship intents: platonic, open to romance, established
  relationship, and let it develop naturally. Non-established starts default to
  stranger social status, no romantic status, and a neutral current dynamic,
  without implied shared history. Established starts require explicit social and
  romantic starting statuses. Reject romantic states under platonic intent.
  Supporting dimensions and boundaries use validated qualitative values; capture
  their initial vocabulary and compatibility cases in Slice 3. Every snapshot
  records user-selected/default origin, without synthetic narrative milestones.
- Archiving is explicit and makes an Ongoing continuity read-only. Starting a
  replacement requires a new confirmation and fresh relationship state; it never
  silently archives an existing active continuity. Reactivation is deferred.
  Identity and persona freezing remain permanent even after all their continuities
  are archived; there is no unfreeze operation.
- Stage 4 exposes only Ongoing creation. Storyline and Timeline may exist in the
  mode enum but their creation requests are rejected until their stages ship.
- Preserve completed messages as append-only records. A failed generation may be
  continued for its existing unmatched user message without creating another
  user message. This recovers an incomplete turn; it cannot regenerate a completed
  persona response or consume Stage 5's response-alternative allowance.
- Use Characters-owned prompts in this order: persona core, identity,
  relationship intent/starting state, applicable current-state inputs, fixed
  response presentation, then summary and recent messages. Omit the empty memory
  slot and scene setup absent from Ongoing. Stage 4 has no style controls or
  conversation-driven state evolution.
- Keep summaries derived and continuity/conversation-scoped. They cover only
  committed complete turns on the sole path. Retain immutable source checkpoints
  so Stage 5 can add branch-aware eligibility/invalidation through a later
  migration rather than treating a summary as global memory.

## Delivery and verification rules

Implement slices in sequence. Each slice is a cohesive change that can be tested
and inspected locally on top of completed predecessors, leaves the application
runnable, and does not depend on a later slice to satisfy its own acceptance
criteria.
Earlier backend slices can leave the Characters landing page in place.

For every implementation slice:

- Add focused tests under `tests/characters/domain/`, `application/`,
  `infrastructure/`, or `ui/`, with service/repository scenarios under
  `tests/integration/characters/`. Extend `tests/architecture/` when boundaries
  change. Keep existing Chat tests intact except for necessary fixture or shell
  assertion adjustments.
- Keep business rules in Characters application services, repository and gateway
  protocols in its domain, SQLAlchemy access in repositories, provider SDK access
  in infrastructure, and composition in Characters infrastructure. UI calls
  application services; the shared shell only routes areas.
- Use complete type hints, absolute imports, repository docstring conventions,
  and concise `doc` descriptions on every persistence column and relationship.
- Run focused unit/integration tests and `scripts/check.sh`. Ordinary tests use
  isolated databases and fake/mocked providers, without running Ollama or cloud
  APIs. Streamlit tests use application-service doubles.
- Document configuration, migrations, and visible behavior introduced by the
  slice. Keep each stage on its own branch. There is no PR workflow; record local
  verification here and retain screenshots for UI changes when applicable.

For each persistence slice, add a new revision under `alembic/characters/versions/`
and run it through `alembic-characters.ini`. Never edit the applied baseline,
Chat migrations, or legacy history. Verify fresh upgrade, upgrade from the prior
Characters head, downgrade to that head, and re-upgrade on disposable PostgreSQL.
Compare Chat schema objects, representative Chat rows, and `chat.alembic_version`
before and after. Render offline SQL and reject cross-schema references.

SQLite repository tests may provide fast portable coverage, but PostgreSQL tests
are required for partial uniqueness, row locking, race outcomes, and migrations.
Provide an explicit test database setting/marker and documented disposable setup;
normal tests must not connect to the development database. The slice's local
database validation run must actually run the PostgreSQL cases, not count skipped
concurrency tests as verification.

## Slice sequence

| Slice | Self-contained outcome | Depends on | Database impact |
|---|---|---|---|
| 1 | Create, edit, list, and duplicate editable identities | Existing scaffold | Identity migration |
| 2 | Create, inspect, list, edit before use, and duplicate persona cores | 1 | Persona migration |
| 3 | Start, resume, and archive isolated Ongoing continuities | 1–2 | Continuity, conversation, starting-state migration |
| 4 | Resolve Characters response/summary providers independently | 1–3 | None |
| 5 | Persist and stream durable Ongoing turns with failure recovery | 3–4 | Message and generation migration |
| 6 | Compress long Ongoing context within a deterministic budget | 4–5 | Rolling-summary migration |
| 7 | Define a replaceable, versioned evolution strategy seam | 3–6 | None; no evolution writes |
| 8 | Confirm starts and navigate Identity → Persona → Ongoing | 1–3 | Existing repository operations only |
| 9 | Converse, resume, and recover in the Ongoing UI | 4–8 | Existing repository operations only |
| 10 | Prove the Stage 4 milestone and independent operation | 1–9 | Verification only |

### Slice 1 — Identity values and management

Status: Complete

Implement identity values, validation, Characters-owned repository protocols,
SQLAlchemy mapping, migration, and application operations to create, list, inspect,
edit before use, and duplicate identities. Include frozen-state representation
and reject editing a frozen record; Slice 3 supplies the first-use transition.
Provide idempotent default **You** setup without initializing Characters on the
Chat route.

Use frozen Pydantic authored values and snapshots with stable UUIDs, positive
revision counters, permanent freeze flags, and default designations. Full authored
replacements require an expected revision. Services check edit eligibility;
repositories repeat frozen/revision guards in conditional updates, increment the
revision, and report missing, frozen, or stale identities through typed domain
errors. Slice 3 locks and verifies both selected profile rows and revisions before
freezing them during continuity creation.

Reserve the default designation with a nullable unique database slot independent
of display name; concurrent default insert conflicts return the committed winner.
Duplicates copy only validated authored details, optionally revised, into new UUIDs
at revision 1 with editable, non-default status and no continuity history. No
unfreeze API is provided. UI composition remains assigned to Slice 8.

Establish Characters test fixtures. The current root `tests/conftest.py` imports
Chat metadata eagerly and installs a SQLite PRAGMA on every engine connection.
Make Chat fixture imports lazy or scope them to Chat tests, add a separate
Characters session fixture, and ensure the SQLite hook does not run against
PostgreSQL. Preserve existing test behavior. SQLAlchemy models stay separate from
Pydantic values.

Verification:

- Unit tests validate identity attributes, invalid age/date/timezone inputs,
  and immutable value behavior. Service/repository tests verify editable
  replacements, frozen-edit rejection, and duplication without frozen status
  or relationship history.
- Repository and service integration tests round-trip every field, preserve stable
  identifiers, return deterministic lists, and create **You** once under repeated
  and concurrent setup.
- Architecture tests prove Characters domain imports no outward layers and that
  fixture collection for Characters does not initialize Chat infrastructure.
- Migration checks prove identity tables and foreign keys are Characters-owned.
  Replace the obsolete assertion that Characters metadata is empty with ownership
  and independence assertions as tables are introduced.

Complete when identity management works through the service and real repository,
with its tests passing independently of persona or continuity implementation.

### Slice 2 — Persona core management and edits before first use

Status: Complete

Add persona identifiers and validated authored cores with a display name and
authored definition/traits. Use frozen Pydantic authored values and snapshots with
a stable UUID, positive authored revision, and permanent freeze flag. Implement
Characters-owned create, list, inspect, edit-before-use, and duplicate-with-revisions
operations, repository mapping, and a new migration.

An edit replaces authored fields under the same identifier, requires an expected
revision, and increments the revision. Services check eligibility; repositories
atomically reject missing, frozen, or stale personas through typed domain errors.
All authored fields, including the display name, freeze globally when the first
continuity using the persona is successfully created with any identity. Slice 3
supplies that transactional freeze using the same row/lock and revision protocol.
Archival never unfreezes a persona; there is no unfreeze API.

Duplication copies only authored fields, optionally revised, into a new identifier
at revision 1 with editable status and no continuity history. Keep relationship
adaptation and current state out of the global persona definition. Immutable
snapshots do not prevent authorized persisted replacements, and an authored
revision counter does not require historical core storage.

Verification:

- Unit tests cover required authored content, immutable core values/snapshots,
  edits retaining the identifier and incrementing the revision, and
  duplicate-with-revisions producing a new editable identifier at revision 1.
- Service/repository integration tests prove pre-use edits round-trip, previously
  observed snapshots remain unchanged, and both layers reject frozen/stale edits.
  Duplicates leave the original intact and copy no freeze state, continuity history,
  relationship adaptation, current state, or identity-specific state.
- Repository contract tests reject missing records and competing stale writes;
  PostgreSQL races prove exactly one concurrent edit wins at a given revision.
  After first use, authored changes require a new record, including display edits.
- Migration and architecture checks confirm independent Characters ownership.

Complete when reusable persona cores can be authored, inspected, edited before
use, and duplicated through application services, with frozen/stale guards ready
for Slice 3 and no edits permitted to a core already used by a continuity.

### Slice 3 — Transactional continuity lifecycle and starting relationship

Status: Complete

Add continuity mode/lifecycle values, immutable ownership, relationship intents,
qualitative starting-state values and provenance, and the sole Ongoing
conversation. Define the initial supporting-dimension/boundary vocabulary and
validation table before coding it; do not implement inferred evolution.

Implement start, resume/read, grouped-list, and archive services and repository
operations. The start transaction locks both selected identity and persona rows
in a consistent order, verifies both submitted revisions, permanently freezes both
profiles, and creates the continuity, conversation, and starting relationship
snapshot. Persona freezing applies globally on first use with any identity. Use a
PostgreSQL partial unique index for active Ongoing ownership by identity/persona, in addition
to service checks. Use Characters-only constraints to prevent conversation or
starting-state ownership mismatches. Confirmation idempotency is persisted.

Identity and persona edits must participate in the same lock/revision protocol
as start so an edit racing first use cannot change the confirmed semantics. If an
edit wins, a start with the old revision fails; if start wins, the edit fails as
frozen. An already frozen profile remains eligible for a new continuity at its
current revision. Archive and future message writes must serialize on the continuity so no write commits after archive.
Keep frozen identity and persona ownership immutable in repository write APIs.

Verification:

- Unit tests cover every intent, valid/invalid starting-state combination,
  archived lifecycle behavior, unsupported-mode rejection, and immutable
  identity/persona/mode bindings.
- Service/repository integration tests prove start commits all records together;
  an injected failure rolls everything back, including newly applied identity and
  persona freezing. Previously frozen profiles remain frozen.
- PostgreSQL races cover two starts for the same pair, default setup/start,
  identity edit versus start, persona edit versus start, and two identities first
  using the same persona. Archive-versus-message races arrive in Slice 5 with the
  actual message repository operations. Exactly one active continuity survives for
  the same pair; distinct pairs may both start with the same frozen persona.
  No start commits against a stale reviewed identity or persona revision.
- Repeated identical confirmation returns the original continuity. Conflicting
  reuse, a stale draft, and a second active start produce typed errors.
- Archive, then explicitly start a replacement: old history remains readable,
  both profiles stay frozen, and the new starting state is independent. First use
  with one identity prevents persona edits for every other identity, including
  display fields.
- Two identities sharing a persona and two archived/current continuities for one
  pair cannot read or change each other's relationship or conversation records.
  An established start has user provenance and no invented milestone events.
- Migration tests exercise the active-only uniqueness constraint directly.

Complete when start/resume/archive works transactionally through real repositories
and lifecycle/ownership failures are deterministic under concurrency.

### Slice 4 — Characters-owned LLM capabilities and Ollama adapter

Status: Complete

Define narrow domain protocols for streaming persona responses, summary generation,
provider/model resolution, and token counting. Add immutable effective generation
configuration and model budget/capability values plus Characters-owned errors.
Provide an Ollama adapter and configured resolver in Characters infrastructure.
Response and summary capabilities may use separately configured local models.

Keep provider clients, model configuration, authentication, and normalized failures
in infrastructure. Share only genuinely generic low-level utilities if useful;
do not import Chat token counters, registries, gateway contracts, or prompts.
Keep area composition lazy. No cloud adapter or additional vendor dependency is
needed in this stage.

Verification:

- Unit tests validate model lookup, effective configuration, output-token reserve,
  unsupported capabilities/parameters, and safe error normalization.
- Adapter contract tests use a mocked Ollama client and a fake second response
  provider; both stream through the same Characters contract. A response-only
  provider need not implement summarization.
- Tests cover error before output, error after partial output, stream closure,
  summary parsing, and token accounting without network calls.
- Architecture tests reject SDK imports in domain/application/UI and Chat imports
  anywhere in Characters; selecting Chat does not construct Characters clients.

Complete when Characters can select and invoke replaceable response and summary
adapters without a Chat service or a running external model.

### Slice 5 — Durable Ongoing turns, streaming, and incomplete-turn recovery

Status: Complete

Add immutable user/persona message values and persistence plus a Characters-owned
generation ledger. Record submitted input, effective provider/model/configuration,
timestamps, pending/streaming/completed/failed/interrupted status, and incomplete
output separately from committed persona messages. Use deterministic message
ordering on the sole path; parent-node/selected-leaf APIs remain Stage 5 work.
Persist current provider/model/requested defaults on the conversation; changing
them affects the next attempt and never rewrites past effective snapshots.

Implement send, stream, inspect history, resume/reconcile abandoned attempts, and
continue-incomplete-turn services. Atomically create the user message and attempt;
atomically commit the persona message and completed attempt. Allow one open
attempt and one unmatched user tail per conversation. Recovery reuses that tail,
retains historical attempt provenance, and never modifies a completed message.
Reject another send until the tail completes, and reject writes to archives.

Use Characters-owned prompt assembly and a minimal deterministic token-budget
policy: reserve fixed prompt overhead and output capacity, include the required
prompt blocks and complete recent history, and reject overflow before generation.
Slice 6 adds summary compression rather than introducing an unbounded interim
prompt path. Provider calls occur outside database transactions; completion
rechecks continuity writability and ownership before committing.

Verification:

- Unit tests cover prompt ordering, intent/starting-state inclusion, input
  validation, budget overflow, lifecycle transitions, and partial-output exclusion.
- Integration tests stream a complete turn, reload it in a fresh service/session,
  and verify exact history and immutable generation provenance.
- Failure-before-output, partial failure, consumer cancellation, and abandoned
  attempts leave no completed persona response. Continuation creates one response
  for the existing user message, with no duplicate user or completed response.
- Concurrent send/completion and archive-during-generation tests prove the open
  attempt limit and prevent a persona message committing after archive.
- Context and history queries reject foreign continuity/conversation identifiers.
  Records from another continuity or Chat never reach a fake provider's captured
  input. Completed messages cannot be edited or regenerated by this API.
- No memory extraction or relationship/persona mutation runs after completion.
  Migration checks verify ownership, attempt constraints, and both atomic writes.

Complete when durable Ongoing conversation works through a fake and mocked Ollama
adapter, including restart, interruption, and isolated incomplete-turn recovery.

### Slice 6 — Rolling summaries and deterministic context budgeting

Status: Complete

Add immutable summary revisions with conversation/continuity ownership, predecessor,
last covered complete-turn checkpoint, and generation provenance. Persist one
active revision per conversation through atomic replacement. Add a Characters
summary gateway prompt and application service separate from context eligibility
and token budgeting.

Use a deterministic policy recorded before implementation: reserve mandatory
prompt blocks and output capacity; retain the latest complete turn and current
user message; select additional complete turns newest-first within the budget,
then render them chronologically. Compress an uncovered older complete-turn prefix
when full eligible history would overflow, using the prior summary plus only new
covered turns. Never split arbitrary messages or inject covered turns twice.
If mandatory blocks, the retained tail, or the resulting summary cannot fit,
return a typed context-capacity failure before response generation.

A summary failure leaves its prior active revision intact. Use the existing
summary only if it and all required uncovered context still fit; otherwise expose
a recoverable context failure, without sending an oversized or silently incomplete
prompt. Incomplete attempts/partial output never enter summary inputs. Protect
replacement with an expected-checkpoint/revision check to reject stale writers.

Verification:

- Unit tests cover exact block order, token boundaries/output reserves, retained
  recent turns, chronological rendering, compression inputs, oversized current
  input, and summary failure policy with fake counters/gateways.
- Service/repository integration tests force multiple summary revisions and prove
  monotonic checkpoints, active-revision uniqueness, no duplicate coverage, and
  atomic replacement/rollback. Concurrent stale replacement cannot win.
- A fresh service resumes the saved summary and uncovered tail with no dependency
  on Streamlit session state. Two continuities with the same identity/persona
  cannot share summaries or consume each other's turns.
- Failed/interrupted generation never changes the complete-turn checkpoint.
  Summary generation or persistence failure preserves committed conversation
  history and exposes the documented recovery behavior.
- Tests prove Ongoing neither creates memory rows nor invokes extraction, and
  summary queries require both conversation and continuity ownership.
- Migration checks cover source ownership and independent Characters history.

Complete when long Ongoing conversations remain bounded and resumable using their
own durable summary, with deterministic failure behavior and no extracted memory.

### Slice 7 — Versioned evolution strategy interface

Status: Complete

Define a Characters-owned application strategy interface with a stable name and
version, immutable scoped inputs, and structured proposal outputs. Inputs carry
identity/persona/continuity references, core and starting-state snapshots, and
eligible conversation evidence. Outputs describe proposed adaptation or
relationship changes with source references; they do not contain persistence
models or mutate repositories.

Provide a baseline no-change strategy and a test implementation proving
substitution. Stage 4 does not invoke experimental evolution after turns or apply
proposals. Stage 7 will implement transition validation, proposal persistence,
append-only events, projections, and corrections; this slice establishes the seam
without claiming those safeguards already exist.

Verification:

- Unit contract tests require stable strategy identity/version, immutable inputs,
  scoped evidence references, and structured outputs traceable to that version.
- A composition/integration test substitutes a test strategy using only Characters
  contracts and fixtures, without constructing Chat, an SDK, or a database client
  inside the strategy.
- The production Ongoing workflow leaves starting relationship state and persona
  cores unchanged after turns; a proposal cannot become durable state through
  existing service APIs.

Complete when the future strategy can be replaced and tested within Characters
without adding Stage 7 evolution behavior to Stage 4.

### Slice 8 — Confirmed start flow and grouped navigation

Status: Proposed

Replace the landing page with Characters-owned UI and lazy infrastructure
composition. Show Identity → Persona → Ongoing groups, active and archived
continuities, and the current identity/persona/mode visibly. Support default
**You**, inline identity and persona creation/editing before use, duplication of
both profiles, and selection through application services.

Implement the start form: identity, persona, Ongoing mode, relationship intent,
optional established-state inputs, then a review/confirmation step. Explain what
carries forward and that Ongoing has no extracted memory. Confirmation alone
calls start; retain its request identifier and both reviewed profile revisions
across reruns. Explain that confirmation permanently freezes both profiles and
that later authored changes require duplication. Handle stale profiles,
active-continuity conflicts, and validation errors without double creation.
Allow explicit archive and resume/read selection; an archive never starts a new
continuity implicitly. Keep all widget/session keys Characters-owned.

Verification:

- Streamlit tests cover empty setup, **You**, inline creation, identity/persona
  edits before use, frozen-edit handling and duplication for both profiles, all
  intents, established-state review, cancel, confirm, and repeated reruns.
  Selection and cancel neither create continuity nor freeze either profile.
  Edits after review produce a stale confirmation requiring renewed review.
- UI service-call assertions prove grouped selection uses the correct ownership
  identifiers and archive/active-conflict outcomes remain visible.
- An integration test exercises the reviewed application request through real
  repositories and returns the confirmed continuity for selection.
- Shell tests switch areas and preserve each area's selection without calling the
  other area's service factory. Replace scaffold-specific Characters assertions
  while retaining their no-Chat-initialization guarantee.

Complete when users can create/select profiles, deliberately start or archive
Ongoing, and navigate its history without UI database/provider access.

### Slice 9 — Ongoing conversation and recovery UI

Status: Proposed

Render saved history and streaming persona replies for the selected continuity.
Restore its configured model selection, relationship starting state, and history
on resume. Apply supported generation configuration to the next attempt through
application services. Show incomplete output separately, support continuation of
the unmatched turn, and report provider/context/summary errors with useful actions.

Disable sending while an attempt is active or a continuity is archived. Archived
history remains readable. Do not expose completed-response retries, branch controls,
memory controls, inferred relationship changes, or response-style controls.

Verification:

- Streamlit tests cover new and resumed turns, streamed chunks, model selection,
  immutable prior provenance, failure, interruption, unmatched-turn continuation,
  context-capacity errors, and archived read-only history.
- Switching between identities/continuities and between product areas does not
  render stale transcript, starting state, or partial output from another scope.
- Service/repository integration tests cover the same request sequence after a
  fresh service restart, including a conversation that has a saved summary.
- UI architecture checks reject SQLAlchemy, provider SDK, repository, and Chat
  service imports. Shell routing initializes only the selected area.

Complete when the complete Ongoing workflow is usable through the UI with durable
resume and visible incomplete-turn recovery.

### Slice 10 — Stage 4 acceptance and independent-operation proof

Status: Proposed

Add one milestone integration scenario covering profile setup, authored edits to
both profiles before use, confirmation, first-use freezing of both, streamed turns,
rolling summary, restart/resume, failed-turn continuation, archive, and explicit
fresh start for the same identity/persona.
Add negative ownership cases beside that scenario and close gaps found by it.

Run Characters services and tests in an isolated process that rejects Chat module
imports. Verify metadata and all foreign keys are Characters-owned, repository
queries stay within its schema, and no shared business prompts/contracts appeared.
Run the complete Characters migration chain on disposable PostgreSQL alongside an
unchanged populated Chat schema. Document Characters settings, local Ollama setup,
both area migration commands, and the new workflow in README/design documentation.

Verification:

- Unit and integration suites demonstrate all Stage 4 invariants, including
  concurrent edits and first use/start for both profiles, permanent global persona
  freezing across identities and archival, archived writability, immutable profile
  ownership, summary provenance, and independent starting states across continuities.
- The milestone runs with deterministic fake providers; a documented local Ollama
  smoke run confirms streaming when the configured service is available, without
  making ordinary tests depend on it.
- PostgreSQL migration/concurrency tests execute successfully. Chat objects, rows,
  and migration head are unchanged; legacy migrations remain untouched.
- Existing Chat regression tests, both-area shell tests, architecture checks, and
  `scripts/check.sh` pass. Characters can be tested and composed without Chat.
- The delivered feature has no extracted Ongoing memory and no prematurely exposed
  Stage 5–8 workflows. Record remaining work in its owning later stage.

Complete when the master Stage 4 completion criteria are demonstrated by automated
tests and documented operation. Only then update this stage, its delivered slices,
and the master Stage 4 status to Complete.

## Deferred scope

- Stage 5: parent-message graphs, selected conversation leaves, completed persona
  response alternatives, the visible three-retry limit, branch actions, and
  branch-correct summary handling/provenance.
- Stage 6: Storylines, ordered scenes, extracted continuity memories, temporal
  eligibility, and memory inspection/correction/exclusion/deletion.
- Stage 7: relationship events/projections, validated inferred transitions,
  milestones/hysteresis, adaptation persistence, correction, and experiments.
- Stage 8: Timeline day records/closure/forks, timezone changes/DST, and adjustable
  response-style controls with per-response effective style.
- Stage 9: broad hardening, observability, export/deletion, and standalone packaging.
  Stage 4 still supplies the isolation and PostgreSQL tests needed to verify its
  own behavior now.
- Characters cloud adapters require their own applicable provider decision;
  legacy data conversion remains superseded, not deferred.
