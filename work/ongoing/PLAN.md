# Stage 3 Execution Plan

Status: In progress

Last updated: 2026-09-19

## Scope

Deliver automatic Chat context and memory as described by Stage 3 of the master
execution plan. This stage owns final Chat summary and memory contracts, durable
rolling summaries, provenance-aware Chat-wide memory, explicit context
eligibility and token budgeting, user memory controls, and the first cloud
response-provider adapter.

The repository already has useful pre-Stage 3 prototype behavior, but Stage 3
redesigns and supersedes it:

- summaries are generated transiently and are not scoped or checkpointed in
  persistence;
- memory is a globally unique key/value store without source provenance or
  lifecycle state;
- memory injection, context sizing, and summarization are combined across the
  current `MemoryService` and `DefaultContextBuilder` paths;
- completed-turn extraction receives the message list captured before the
  assistant response is committed; and
- context estimation does not reserve the selected model's output allowance or
  define deterministic eligibility and omission rules.

Stage 2's initial recovery model also permits multiple incomplete attempts to
remain independently actionable. Stage 3 narrows that behavior to a linear Chat
conversation with one unmatched tail and one current retry target. Historical
terminal attempts remain inspectable without becoming resumable branches.

Stage 3 replaces those provisional behaviors rather than adding a second context
or memory path. Chat remains independent of Characters. Cloud response selection
uses the Stage 2 provider registry, while title generation, summarization, and
memory extraction may continue to use the independently configured Ollama
utility adapter.

The prototype database schema is a structural starting point only. Its old test
data has already been deleted, so Stage 3 has no legacy-row preservation,
backfill, or conversion requirement.

## Delivery rules

Implement the slices in order. Each slice is a separate review and approval unit,
keeps Chat runnable, and leaves the full suite passing. A slice is complete only
when its acceptance criteria are automated where practical and its status is
updated from Planned to Complete.

For every slice:

- add focused unit tests beside the affected Chat layer;
- add integration tests when a service crosses a repository boundary;
- use only Chat-owned contracts, prompts, repositories, models, and migrations;
- keep SQLAlchemy access inside repositories and provider SDK access inside
  infrastructure adapters;
- use `uv add` or `uv remove` for dependency changes; and
- run `scripts/check.sh` before completion.

For migration slices, also render the Chat migration history, upgrade and
downgrade a disposable PostgreSQL database, and verify that the `characters`
schema and `characters.alembic_version` are unchanged. Never edit an applied
migration.

## Slice sequence

| Slice | Outcome | Database impact |
|---|---|---|
| 1 | Freeze automatic-context and memory behavior | None |
| 2 | Revise Chat domain contracts and linear-turn service seams | None |
| 3 | Persist linear retries, summaries, and memory lifecycle | Chat migration |
| 4 | Extract memory with bounded completed-turn processing | Chat data writes only |
| 5 | Add memory-management workflows | Chat data writes only |
| 6 | Add memory inspection and controls to the Chat UI | None beyond slice 5 |
| 7 | Persist conversation-scoped rolling summaries | Chat data writes only |
| 8 | Assemble eligible context within the selected model budget | None beyond slice 3 |
| 9 | Select the first cloud provider | None |
| 10 | Add the selected cloud response adapter | Configuration; dependency only if required |
| 11 | Prove the Stage 3 milestone and remove provisional paths | None |

### Slice 1 — Freeze automatic-context and memory behavior

**Status: Complete.**

Delivered by accepted ADRs 017–020, the 2026-09-19 in-place revisions to ADRs
016–020, and the corresponding Chat design update.

Write and accept focused ADRs before changing persistence or orchestration. The
ADRs must turn the Stage 3 outcomes into deterministic rules and update the Chat
sections of `DESIGN.md` when they are accepted.

The recommended decision is:

- Chat history is linear. One attempt may be pending or streaming, and only the
  latest failed or interrupted attempt for the unmatched final user message is
  retryable. A new message is rejected until that tail completes. Editing the
  unmatched tail is allowed while no attempt is open, and every attempt retains
  its immutable submitted-content snapshot.
- A rolling summary is conversation-owned and versioned. One version is active;
  a replacement supersedes it. Its provenance identifies its predecessor and
  last fully covered assistant message. ADR 016's linear completion order makes
  that checkpoint authoritative without per-attempt summary-source records.
- Summary updates consume the prior active summary plus newly eligible complete
  turns. They never consume another conversation's messages, an incomplete
  attempt, partial output, or the current unmatched user message.
- A Chat memory is a durable statement with a stable identifier, lifecycle
  state, timestamps, and origin. Extracted origins identify the source
  conversation, user message, assistant message, and completed generation
  attempt. Corrected origins explicitly record their user-authored provenance.
- Correction creates a replacement and atomically supersedes the prior memory.
  Exclusion is reversible and removes a memory from prompt eligibility. Hard
  deletion physically removes the selected memory and its provenance. The ADR
  must reconcile hard deletion with the requested `deleted` lifecycle state—for
  example, by treating deletion as a terminal transition immediately followed
  by purge, rather than retaining a tombstone that contains user data.
- Extraction is bounded best-effort processing after response completion. It
  makes at most three processing attempts, then records either `succeeded` or
  `exhausted`. A terminal attempt-level receipt prevents repeated callbacks from
  invoking the utility provider again without storing per-memory effect records.
- The empty prototype key/value table may be altered or replaced by a new Chat
  migration. No prototype rows are converted, backfilled, or preserved.
- Context eligibility and token budgeting are separate. Eligible inputs are
  active Chat memories, the selected conversation's active summary, and that
  conversation's uncovered recent messages. The budget reserves fixed prompt
  overhead and the effective maximum output tokens before selecting prompt
  content. The ADR defines a per-model output reserve when the caller leaves
  `max_output_tokens` unset, so the prompt budget is never based on an unknown
  completion size.
- Context ordering, whole-item omission, minimum recent-turn retention, rolling
  summary trigger, oversized-current-message behavior, and utility-generation
  failure behavior are deterministic and covered by behavioral examples. No
  component silently slices arbitrary text merely to fit.

Acceptance:

- The ADRs are Accepted and have examples for a long conversation, a failed and
  edited retry, concurrent-send rejection, bounded extraction exhaustion,
  cross-conversation memory reuse, memory correction and exclusion, hard
  deletion, an oversized prompt, and summary failure.
- `DESIGN.md` agrees with the ADRs on summary scope, memory lifecycle, provenance,
  and budget ordering.
- The schema transition explicitly requires no prototype-data preservation.
- No implementation-critical policy choice is deferred to a later coding slice.
- Production behavior and database objects are unchanged.

### Slice 2 — Revise Chat domain contracts and linear-turn service seams

**Status: Complete.**

- Preserve the accepted memory lifecycle, memory origin, context-budget, and
  provider-capability values that remain valid.
- Add immutable submitted-user-content provenance to generation attempts and
  define the singular open and retryable attempt concepts from ADR 016.
- Replace unresolved-attempt collections with repository operations for one open
  attempt, one unmatched tail, one latest retry target, and editing that tail
  only while no attempt is open.
- Simplify summary provenance to conversation ownership, predecessor, and one
  authoritative assistant-message checkpoint. Remove `SummarySource` and
  newly-covered-attempt collections from domain and repository contracts.
- Replace extraction-effect results with a minimal terminal processing receipt
  containing the completed attempt, `succeeded` or `exhausted` outcome, attempt
  count, and completion time.
- Keep narrow application-facing seams for context eligibility, token budgeting,
  rolling summarization, and completed-turn memory extraction. Provider
  contracts remain capability-specific and persistence-neutral.
- Adapt application and infrastructure compatibility paths enough to keep Chat
  runnable while Slice 3 implements the final constraints and repositories.

Acceptance:

- Domain tests cover attempt snapshots, summary checkpoint progression, receipt
  outcomes, memory provenance, and every legal memory lifecycle transition.
- Contract tests prove plural unresolved retry targets and summary-source graphs
  no longer exist.
- Fake repositories prove a conversation exposes at most one open attempt and
  one latest retry target.
- A fake eligibility service supplies inputs without a token counter, and a fake
  budgeter assembles supplied inputs without a repository.
- Chat domain imports no application, infrastructure, UI, or Characters module.
- The application remains runnable without introducing final database objects
  ahead of Slice 3.

### Slice 3 — Persist linear retries, summaries, and memory lifecycle

**Status: Planned.**

- Add immutable submitted-user-content snapshots to generation attempts and a
  partial unique constraint allowing at most one pending or streaming attempt per
  conversation.
- Implement transactional operations for starting a new linear turn, loading the
  singular open or retryable attempt, editing the unmatched tail, retrying it,
  and rejecting a new message until it completes.
- Add Chat SQLAlchemy models for checkpointed versioned summaries, final memory
  revisions, and minimal terminal extraction receipts. Give every mapped field
  and relationship a concise `doc` description.
- Persist summary predecessor lineage and an authoritative assistant-message
  checkpoint without a summary-source association table.
- Enforce conversation ownership and source provenance with Chat-schema foreign
  keys only. Add constraints and indexes for one active summary per conversation,
  legal memory lifecycle/provenance combinations, deterministic ordering, and
  one terminal extraction receipt per completed attempt.
- Implement summary and memory repository adapters, including atomic summary
  replacement, memory correction/supersession, exclusion/reactivation, eligible
  queries, source inspection, and hard deletion.
- Add a new Chat migration after `82e6c4f63a91`. Alter or replace the empty
  prototype memory table as appropriate; do not add conversion or backfill logic
  and do not change either the Stage 1 baseline or the Stage 2 migration.
- Keep application services on repository protocols and keep schema-specific
  translation inside the adapters.

Acceptance:

- Repository tests cover concurrent open-attempt rejection, failed-tail editing,
  latest-attempt retry selection, successful tail completion, summary replacement
  and checkpoint ordering, receipt uniqueness, memory provenance, lifecycle
  transitions, correction races, eligible filtering, and hard deletion.
- Database constraints reject a second open attempt, cross-conversation summary
  checkpoints, and invalid memory source-message or completed-attempt
  combinations.
- Fresh databases and databases upgraded from the empty prototype schema produce
  the same final Chat objects.
- Chat upgrade, downgrade, and re-upgrade work on disposable PostgreSQL.
- Offline migration SQL contains only `chat` objects; the Characters schema and
  migration head are unchanged.

### Slice 4 — Extract memory with bounded completed-turn processing

**Status: Planned.**

- Replace interval-based history extraction with a dedicated completed-turn
  extraction service.
- Invoke extraction only after the assistant message and completed generation
  attempt commit. Pass the exact user/assistant pair and their provenance rather
  than a pre-completion copy of conversation history.
- Validate and normalize utility-provider candidates before persistence. Apply
  the accepted duplicate, conflict, and supersession policy transactionally.
- Attempt the complete extraction process at most three times. Roll back a failed
  candidate transaction before retrying, then persist an `exhausted` receipt and
  give up without background or later automatic repair.
- Persist candidate changes and a `succeeded` receipt atomically, including when
  the valid candidate set is empty. A repeated callback observes either terminal
  receipt and performs no utility-provider or repository work.
- Treat extraction as best-effort post-completion work: failure is logged and
  test-visible but never changes a completed assistant response into an
  incomplete attempt.
- Remove the extraction-interval setting if Slice 1 makes every completed turn
  eligible; otherwise rename and document the accepted trigger policy.

Acceptance:

- Tests prove extraction receives one exact completed pair including the
  assistant response.
- Pending, streaming, failed, and interrupted attempts create no memories.
- Successful response retry extracts only from its completed attempt and exact
  edited user content when applicable.
- Utility, parsing, validation, and persistence failures stop after three total
  attempts and persist one exhausted receipt.
- Re-running completed-turn processing after either terminal outcome is a no-op.
- No per-memory extraction-effect records are created.
- A memory extracted in one conversation is returned by the Chat-wide eligible
  query for another conversation, with its original provenance intact.

### Slice 5 — Add memory-management workflows

**Status: Planned.**

- Add application schemas and a dedicated memory-management service for listing
  memories, inspecting provenance, correcting content, excluding and
  reactivating a memory, and hard-deleting a memory.
- Return source conversation and source-message information through application
  read models without exposing SQLAlchemy entities to the UI.
- Make correction create a replacement with explicit correction provenance and
  atomically supersede the previous active memory.
- Ensure lifecycle actions are stable when repeated and report missing or stale
  targets without partially changing state.
- Keep extracted-memory orchestration separate from user-initiated management.

Acceptance:

- Application tests cover listing by state, source inspection, correction,
  exclusion, reactivation, deletion, missing targets, and concurrent/stale
  transitions.
- Corrected content is immediately eligible and the superseded content is not.
- Excluded, superseded, and deleted memories are absent from eligible queries.
- Hard deletion removes the selected stored content and provenance as specified
  by Slice 1.
- No management service issues a SQLAlchemy query or imports infrastructure.

### Slice 6 — Add memory inspection and controls to the Chat UI

**Status: Planned.**

- Add a Chat-owned memory-management view reachable without selecting a
  conversation.
- Show memory content, lifecycle state, origin, source conversation, source turn,
  and timestamps in a compact inspection flow.
- Add explicit correction, exclusion/reactivation, and hard-deletion actions.
  Require confirmation before hard deletion and explain that it is irreversible.
- Refresh eligible context inputs after a management action without constructing
  repositories or provider adapters in the page.
- Keep memory controls in Chat UI; do not add them to the shared shell or
  Characters.

Acceptance:

- Streamlit tests cover empty state, extracted and corrected provenance,
  unavailable source provenance, correction, exclusion, reactivation, confirmed
  deletion, and cancelled deletion.
- A correction or exclusion is reflected on the next response boundary.
- The UI calls application services only and does not import persistence models.
- Conversation selection, generation selection, streaming, and recovery still
  work as in Stage 2.

### Slice 7 — Persist conversation-scoped rolling summaries

**Status: Planned.**

- Add a rolling-summary service that loads only the selected conversation's
  active summary and complete turns after its checkpoint.
- When the accepted trigger is reached, summarize the prior active summary plus
  the oldest newly eligible complete turns, retain the required recent turns,
  and atomically persist the replacement summary and new checkpoint.
- Never summarize the current unmatched user message, partial output, failed or
  interrupted output, or a turn at or before the active checkpoint.
- Make repeated invocation at the same checkpoint a no-op and reject checkpoint
  regression.
- Preserve the prior active summary if utility generation or persistence fails;
  apply the fallback behavior accepted in Slice 1.

Acceptance:

- Unit tests cover first summary, rolling replacement, no-op invocation,
  checkpoint regression, utility failure, and retry after failure.
- Integration tests prove summary versions and checkpoint messages belong to one
  conversation and deletion follows the accepted ownership rule.
- Resuming a conversation uses its persisted active summary without regenerating
  already covered turns.
- Two long conversations never read, update, or include each other's summaries.

### Slice 8 — Assemble eligible context within the selected model budget

**Status: Planned.**

- Implement a context-eligibility service that retrieves active Chat-wide
  memories, the selected conversation's active summary, and uncovered messages
  in deterministic order.
- Implement a separate token-budget service that uses the selected
  `ModelDescriptor` token counter and context-window limit. Reserve prompt
  overhead and the effective or model-default output-token allowance before
  admitting eligible components.
- Orchestrate rolling summarization when eligible conversation content crosses
  the accepted trigger, then reload eligibility and budget the resulting
  summary, recent messages, and memories.
- Apply the accepted priority and whole-item omission rules deterministically.
  Raise a Chat-owned error when mandatory content cannot fit rather than sending
  an oversized provider request.
- Make synchronous generation, streaming generation, and retry use the same
  assembly path, exclude incomplete output, and include an unmatched retry tail
  exactly once as current input.
- Retire memory injection and transient half-history summarization from
  `MemoryService` and `DefaultContextBuilder`. Remove the obsolete combined
  `LLMGateway` compatibility contract once composition uses only
  capability-specific protocols.

Acceptance:

- Budget tests cover exact fit, output reservation, overhead, memory omission,
  recent-turn retention, summary inclusion, oversized mandatory content, and two
  models with different windows and token counters.
- Context tests prove only active memories are eligible, summaries are
  conversation-local, covered messages are not duplicated, and ordering is
  stable.
- Long-conversation integration tests cross multiple summary checkpoints while
  preserving recent context and staying within the selected model budget.
- A memory extracted in conversation A can appear in conversation B, while A's
  summary and messages cannot.
- No provider is invoked with context above its declared prompt budget.

### Slice 9 — Select the first cloud provider

**Status: Planned.**

Create and accept the focused cloud-provider ADR required by ADR 014. Do not
infer a vendor merely from a currently installed dependency.

- Compare viable providers against Stage 2's response contract and Stage 3's
  local-first goal, then select exactly one.
- Record authentication and credential discovery, endpoint/region configuration,
  supported model identifiers, streaming behavior, generation-parameter mapping,
  context limits, token estimation, normalized errors, timeouts, and data
  handling implications.
- Define opt-in registration and startup behavior when credentials are absent so
  Ollama-only operation remains functional.
- Decide whether an SDK dependency is needed and how it will be managed with
  `uv`. Scope the first adapter to visible response generation unless a separate
  utility capability is explicitly justified.

Acceptance:

- The provider ADR is Accepted and contains no unresolved authentication,
  capability, model-metadata, token-counting, or data-handling choice needed by
  the adapter.
- Secret values are excluded from descriptors, persisted generation
  configuration, logs, tests, and UI state.
- The ADR defines mocked contract tests and an optional credential-gated smoke
  test; normal CI requires no network access or cloud account.
- Production code and provider registration are unchanged.

### Slice 10 — Add the selected cloud response adapter

**Status: Planned.**

- Implement the selected Chat infrastructure adapter against `ResponseGenerator`
  for complete and streaming responses.
- Translate provider-neutral generation configuration and messages at the
  adapter boundary and normalize SDK failures into Chat-owned exceptions with
  safe user-facing detail.
- Add immutable descriptors and an appropriate token counter for the configured
  cloud models. Register the provider only when its opt-in configuration is
  enabled and valid.
- Add provider-specific settings and documentation without placing credentials
  in source, model descriptors, persistence, logs, or application services.
- Update dependencies through `uv` only when required by the accepted ADR.
- Let the existing Chat provider/model UI discover the cloud provider through
  the registry; do not add vendor branches to application or UI code.

Acceptance:

- The same response-provider contract suite passes for mocked Ollama and the
  mocked cloud adapter, including ordered streaming and configuration mapping.
- Registry and composition tests cover disabled, enabled, misconfigured, and
  credential-absent cloud states while Ollama remains usable.
- Selecting the cloud model records immutable cloud provenance and uses that
  model's token budget; switching later does not rewrite prior attempts.
- Provider errors expose no request headers, credentials, or unsafe SDK payloads.
- The optional live smoke test is documented and skipped unless explicitly
  configured.

### Slice 11 — Prove the Stage 3 milestone and remove provisional paths

**Status: Planned.**

- Add end-to-end scenarios for long local and cloud-backed conversations,
  failed-tail editing and retry, concurrent-send rejection, cross-conversation
  Chat memory reuse, summary isolation, bounded completed-turn extraction,
  correction, exclusion, deletion, and provider switching.
- Strengthen architecture checks for Chat/Characters import and schema isolation,
  application-to-infrastructure dependency direction, provider SDK isolation,
  and the absence of direct SQLAlchemy access from services and UI.
- Verify all provisional key/value memory, transient summary, combined gateway,
  and duplicate context-assembly paths have been removed; retain no compatibility
  path that can bypass provenance, lifecycle, or budgeting rules.
- Update operator documentation for Chat migrations, Ollama utility requirements,
  cloud opt-in configuration, memory controls, and local data versus cloud data
  flow.
- Run the complete repository quality suite and verify every Stage 3 completion
  condition in the master plan.

Acceptance:

- Long conversations remain within the selected model budget and retain coherent
  rolling context across multiple summary updates.
- Active memory is reusable across Chat conversations; non-active memory is not.
- Summaries and ordinary messages never cross conversation boundaries or enter
  Characters.
- Users can inspect provenance, correct, exclude/reactivate, and hard-delete
  stored Chat memory through the UI.
- Ollama and the selected cloud adapter pass the same response contract tests.
- Chat migrations affect only `chat.alembic_version`; Characters tests and
  migrations run without initializing Chat.
- `scripts/check.sh` passes, the master plan's Stage 3 completion criteria are
  satisfied, and Stage 3 can be marked Complete.

## Explicitly out of scope

- Characters identities, personas, continuities, prompts, memory, relationship
  state, migrations, or UI behavior.
- Vector search, embeddings, semantic ranking, memory importance scoring, or an
  external vector database. Deterministic filtering and budgeting are sufficient
  for Stage 3.
- Background workers, scheduled extraction, or asynchronous summary repair.
- Multiple open attempts, multiple retryable tails, response alternatives, or
  branching conversation history in Chat.
- A second cloud provider or cloud implementations of title, summary, or memory
  utility capabilities.
- Editing the Stage 1 Chat baseline, the Stage 2 generation migration, or any
  historical migration file.
- Stage 9 observability and export/deletion hardening beyond the logs, user
  controls, and verification required for Stage 3 correctness.

## Stage completion checklist

- Every slice above is Complete.
- The accepted Stage 3 ADRs and `DESIGN.md` describe the implemented behavior.
- Every conversation has at most one open attempt and one unmatched retryable
  tail; terminal attempt history never creates response branches.
- Context eligibility, budgeting, rolling summarization, and memory extraction
  are distinct Chat application responsibilities.
- Every persisted summary is conversation-scoped and checkpointed.
- Every new extracted or corrected memory has truthful provenance and a tested
  lifecycle; only active memory is prompt-eligible.
- Extraction runs only for complete turns, terminates with a succeeded or
  exhausted receipt within its fixed attempt limit, and is idempotent afterward.
- Context always honors the selected model's token counter, context window,
  output reservation, and deterministic priority rules.
- Both local and cloud response adapters satisfy the shared contract without
  provider-specific application branches.
- Chat and Characters remain isolated in imports, runtime composition, schema,
  migrations, and context data.
- `scripts/check.sh` passes.
