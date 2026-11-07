# Stage 8 Execution Plan — Timeline and Response-Style Controls

Status: In progress

Last updated: 2026-11-07

## Outcome

Add Timeline as the third Characters continuity mode and replace fixed internal
response-style defaults with user-controlled presentation settings.

A Timeline grows through local-calendar-day conversations. It creates a day only
when the first user input and generation attempt are reserved atomically, stores
the resolved local date and timezone with that day, and makes the day permanently
read-only after its local boundary. Current-day messages provide short-term
context; branch- and time-eligible Timeline memory, relationship state, and persona
adaptations provide long-term continuity. Only the latest open day permits retry,
alternative selection, and in-place branching; closed history is permanently
read-only and never forks. Timeline start captures the local-first application's
IANA timezone automatically; the pilot exposes no Timeline timezone control or
persona-local clock.

Response-style controls cover scene-description level, response length, and
narrative placement. A fixed Markdown convention handles description, ordinary
prose, emphasis, quotations, and embedded exchanges without dialogue-format or
tone settings. A saved change affects the next newly reserved persona response,
and every completed persona message retains the exact effective style snapshot
used to generate it. Existing messages and derived memory, relationship, and
persona state are never rewritten.

The stage must preserve these boundaries:

- Timeline data, prompts, repositories, migrations, and UI remain Characters-owned.
- Chat records, schema objects, runtime initialization, and behavior are unchanged.
- Ongoing remains free of extracted long-term memory.
- Storyline and Timeline temporal eligibility uses immutable Entry positions
  within each independent continuity; Timeline calendar policy retains Day date
  and boundary facts. Ongoing remains entryless.
- All persistence access remains behind Characters repository protocols.
- Tests use an injected clock and fake providers; wall-clock timing, local machine
  timezone, Ollama, and network access are not CI requirements.

## Baseline contract to record before implementation

Slice 1 must reconcile ADRs 006, 008, 009, 011, 025, 033, and 039 with the
delivered Stage 6 and Stage 7 behavior. It should add or revise only the focused
decisions needed to settle the following details before schema work:

- A Timeline is an independently owned continuity with one identity, persona,
  starting relationship, lifecycle, automatically captured immutable application-
  local IANA timezone, and optimistic revision.
- A profile pair may own at most one active Timeline. Ongoing and Storyline active
  slots are independent of that Timeline slot.
- Timeline start captures the application's valid local IANA timezone without a
  user-facing timezone field. Identity and persona location do not override it,
  and an existing Timeline cannot be rezoned.
- A represented Day contains its immutable Continuity Entry, which owns profile,
  continuity, mode, conversation, and positive position. Day details own local
  date, boundary timezone, UTC opening and closing facts, closure observation,
  and settled leaf. The exact conversation owns its graph and summary lineage.
  Shared ownership, position, and Day boundary facts never change after creation.
- A day is created with its first user message and pending response attempt in one
  transaction. Merely opening or refreshing the UI creates nothing.
- Closure is determined from the injected current UTC instant and the stored
  boundary facts, then persisted idempotently when observed. A closed day can be
  read but cannot accept input, retry, alternative selection, or an in-place
  branch.
- Persona-local clock display, inferred persona timezones, and sleep or
  availability rules remain outside Timeline calendar behavior and are deferred.
- Only the latest open day permits retry, saved-future selection, and Branch from
  here. Closed and non-latest days return stable read-only reasons and never copy
  the Timeline, profiles, history, derived state, identifiers, or provenance.
- Timeline memory is continuity-scoped, branch-aware, and temporally eligible by
  immutable EntryPosition. Learned Entry is the source Entry; occurrence cannot
  follow learning, and neither position can be later than the target Entry.
  Current-day messages are the only transcript used as short-term response context.
- Relationship and persona evolution run after eligible complete Timeline turns,
  cite exact selected evidence, and rebuild after open-day branch selection under
  the same replay rules as the other Characters modes. Closure freezes the day's
  selected ancestry for later eligibility.
- Response style has a typed, versioned, safe vocabulary and deterministic prompt
  rendering for all three controls. The decision must define allowed values,
  defaults, and scope in Ongoing, Storyline, and Timeline. Dialogue formatting is
  a fixed Markdown convention, while tone remains governed by persona and
  relationship context rather than persisted style.
- Saving style and reserving an attempt use a clear revision boundary. An already
  reserved attempt keeps its immutable style; the next attempt reserved after a
  successful update uses the new style. Retry is a new attempt and therefore uses
  the then-current style while preserving older alternatives.
- Style changes affect presentation only. They do not alter persona core,
  adaptations, facts, memory, relationship state, historical scene setup, or prior
  message provenance.

If implementation would contradict an accepted decision, revise or supersede the
decision explicitly rather than embedding a different rule in code.

## Delivery and verification rules

Implement slices in order unless the dependency table permits parallel work. Each
slice must leave both product areas runnable and must satisfy its own acceptance
criteria without depending on an unfinished later slice.

Domain values and repository protocols belong in `characters/domain/`;
orchestration, calendar policy, context eligibility, and style resolution belong
in `characters/application/`; SQLAlchemy models and repositories belong in
`characters/infrastructure/`; prompts belong in `characters/prompts/`; widgets and
page flow belong in `characters/ui/`. Export main architecture symbols at their
owning package boundaries and retain complete type hints and Google-style
docstrings.

Persistence slices add forward-only revisions under
`alembic/characters/versions/` through `alembic-characters.ini`. Never edit an
applied migration. Test fresh upgrade, upgrade from the Stage 7 head, downgrade to
the preceding head where data loss is understood, and re-upgrade on disposable
PostgreSQL. Render offline SQL and reject references to the `chat` schema. Compare
representative Chat rows, schema objects, and `chat.alembic_version` before and
after Characters migrations.

Time tests must use explicit aware UTC instants and injected named IANA zones.
Cover normal midnights, both DST transitions, zones with non-hour offsets, and
offline gaps. Never patch the process timezone or use sleeps.

Every implementation slice adds focused tests in the matching
`tests/characters/` layer. Add PostgreSQL coverage for constraints, locks, and
races, integration coverage when services cross repository boundaries, and
architecture coverage when package or schema boundaries change. Use deterministic
fake providers except for separately enabled smoke tests.

For each slice, run the smallest relevant checks. Slice 17 runs the CI-equivalent
commands independently:

```bash
timeout 30s uv run black --check src tests
uv run isort --check-only src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -v
```

If Black times out, do not retry it during that run. Continue the other checks and
report the timeout. Fix an ordinary formatting failure and rerun Black once with
the same cap.

## Slice sequence

| Slice | Self-contained outcome | Depends on | Database impact |
|---|---|---:|---|
| 1 | Record Timeline, calendar, branching, and style decisions | Stage 7 | None |
| 2 | Add executable calendar and response-style values | 1 | None |
| 3 | Add Timeline ownership, day, start, and repository contracts | 1–2 | None |
| 4 | Persist Timelines, days, calendar facts, and style settings | 2–3 | Characters migration |
| 5 | Start, resume, and archive Timelines | 4 | Existing Timeline records |
| 6 | Create days atomically and close them deterministically | 4–5 | Existing Timeline/day records |
| 7 | Resolve, update, and snapshot effective response style | 2, 4–6 | Existing style and attempt records |
| 8 | Converse and summarize within an open Timeline day | 6–7 | Existing graph/summary records |
| 9 | Add branch- and time-aware Timeline memory | 6, 8 | Existing memory records or additive migration if required by Slice 1 |
| 10 | Add Timeline Entry-backed relationship and persona evolution | 6, 8–9, Continuity Entry refactor | Existing evolution records |
| 11 | Assemble deterministic Timeline response context | 7–10 | Existing repository operations |
| 12 | Enforce latest-open-day graph actions and closed-history guards | 6, 8–11 | Existing graph and day records |
| 13 | Ship Timeline creation, navigation, day, and archive UI | 5–6, 8 | Existing Timeline/day records |
| 14 | Ship style, memory, evolution, and closed-history guidance UI | 7, 9–13 | Existing records only |
| 15 | Add focused diagnostics and calendar recovery checks | 5–14 | None |
| 16 | Update project documents for shipped Stage 8 behavior | 1–15 | None |
| 17 | Prove the Stage 8 milestone and area isolation | 1–16 | Verification only |

The split keeps schema ownership, calendar policy, derivation eligibility, graph
action policy, and Streamlit state out of the same change. Response-style work
lands before Timeline prompting so every new persona response has correct
provenance from its first end-to-end test.

## Slice details

### Slice 1 — Record durable Timeline and style decisions

Status: Complete

Update ADR 011 and add focused ADRs only where needed to establish the baseline
contract above. Reconcile the result with:

- ADR 006 continuity ownership and mode isolation.
- ADR 008 mode-specific context and memory.
- ADRs 009, 033, and 039 graph actions and mode-specific fork semantics.
- ADR 025 Storyline lifecycle and exact profile duplication.
- ADRs 031 and 032 memory lifecycle and extraction.
- ADRs 034–036 adaptation, replayable evolution, and strategy versions.

Include executable behavioral examples for first interaction, no-interaction days,
offline reopening, DST gaps and folds, automatic application-local timezone
capture, a persona in another location, concurrent first sends, concurrent
boundary crossing, an open-day retry and branch, a rejected closed-day graph
action, a style update before send, a style update during an attempt, and a retry
under a newer style.

Complete when ownership, active-slot rules, day identity, closure, immutable
calendar-zone capture, latest-open-day graph policy, memory/evolution eligibility,
style scope, and attempt snapshot semantics are unambiguous enough to implement
without schema guesses.

### Slice 2 — Add executable calendar and response-style values

Status: Complete

Add immutable Pydantic values for:

- Injected aware-UTC `Clock` behavior and resolved local calendar facts.
- A day boundary containing local date, IANA timezone, UTC opening instant, and UTC
  closing instant.
- An injected application-local IANA timezone source used only at Timeline start.
- The three typed response-style controls, their validated requested settings, and
  a versioned effective `ResponseStyle` renderer.
- Optimistic style revisions and explicit default resolution.

Keep timezone conversion in one Characters-owned calendar policy based on
`zoneinfo`. Reject naive timestamps, an invalid injected local zone, ambiguous
unsupported state, unknown style values, oversized authored values if the ADR
permits them, and instructions that cannot fit the existing snapshot limit. Do
not persist or call a provider in this slice.

Unit-test DST spring-forward and fall-back boundaries, non-hour offsets, year and
leap-day rollover, UTC/local conversion, style defaults, every control, stable
render order, fixed Markdown instructions, rejection of removed dialogue-format
and tone fields, and equivalent snapshot equality.

Complete when calendar decisions and style settings are deterministic pure values
that later services can depend on without reading system time or formatting prompt
text themselves.

### Slice 3 — Add Timeline domain and repository contracts

Status: Complete

Add immutable Timeline, Timeline day, start request, group/navigation snapshot,
and graph-action availability contracts. Extend conversation targets so Timeline
requires a day owner just as Storyline requires a scene owner, while Ongoing
remains ownerless at that level.

Define Characters-owned repository protocols for:

- Starting, loading, listing, revising, and archiving a Timeline.
- Looking up represented days and loading the latest day.
- Reserving the first input and attempt with a new day.
- Observing and persisting closure idempotently.
- Reading and updating current style settings under an expected revision.

Use explicit results for active-slot conflicts, stale revisions, closure races,
duplicate dates, stale leaves, and unavailable graph actions on closed or
non-latest days. Do not leak SQLAlchemy models or session types through the
contracts.

Complete when invalid ownership, lifecycle, day order, captured calendar zone, and
conversation targets fail in domain tests and application code has all persistence
seams needed by later slices.

### Slice 4 — Persist Timeline, calendar, and style state

Status: Complete

Add one reviewed Characters migration and database repository implementations for
the accepted model. At minimum persist:

- Timeline continuity identity, profile ownership, lifecycle, starting
  relationship, captured immutable calendar timezone, and revision.
- Timeline day continuity ownership, immutable position and local date, boundary
  timezone, UTC opening/closing facts, closure observation, conversation ownership,
  and settled selected-leaf guard.
- Current response-style settings and revision at the ADR-defined scope.
- The linkage needed for every generation attempt and persona message to retain its
  immutable effective style snapshot.

Prefer reusing the established continuity, graph, attempt, summary, memory, and
evolution tables where their ownership contracts genuinely match. Add columns or
tables rather than encoding Timeline facts into scene setup or arbitrary JSON.
Enforce one active Timeline per profile pair, unique day ownership/date/position,
aware UTC values, and no cross-mode owner shapes through constraints and repository
validation.

Test fresh and incremental migration paths, offline SQL, constraint failures,
active-slot and first-day races, repository detachment, restart behavior, and Chat
schema preservation.

Complete when Timeline and style state survive restart, invalid rows fail at the
database boundary, and no migration or model references Chat.

### Slice 5 — Start, resume, and archive Timelines

Status: Complete

Implement application services that:

- Review profile revisions and starting relationship, then capture the injected
  application-local timezone during confirmation without exposing a timezone
  field.
- Freeze newly used profiles and create the Timeline atomically and idempotently.
- Preserve independent active slots for Ongoing, Storyline, and Timeline.
- Return stable navigation snapshots without creating a day.
- Archive a Timeline under its expected revision and make all owned state
  permanently read-only.

Cover duplicate confirmations, conflicting request reuse, invalid injected local
zones, active-slot races, stale revisions, and archive/send serialization.

Complete when a Timeline can be started, resumed, and archived without timezone
setup, placeholder days, or effects on other continuity modes.

### Slice 6 — Create days atomically and close them deterministically

Status: Complete

Build one calendar orchestration service around the injected clock. On every
write-capable Timeline operation it must:

1. Load the Timeline and latest represented day under the required lock/revision.
2. Resolve closure from stored boundary facts and the current UTC instant.
3. Persist newly observed closure idempotently, including after an offline gap.
4. Resolve the writable local day under the Timeline's captured calendar timezone.
5. Reuse an open represented day or atomically create a new day together with its
   first user node and pending generation attempt.

Reading an empty or future Timeline creates no row. Do not generate records for
missed days. Reject any operation whose supplied clock instant moves backward
across already committed calendar facts or would violate the monotonic-date rule
accepted in Slice 1.

Add deterministic unit and PostgreSQL integration tests for exact-boundary
instants, DST gaps/folds, multi-day offline periods, captured-zone stability, two
first sends racing, a send racing midnight, closure idempotency, and rollback
after attempt reservation failure.

Complete when exactly one correctly dated conversation is created per interacting
day, no empty days exist, and closed-day writes cannot win a race.

### Slice 7 — Resolve, update, and snapshot effective response style

Status: Complete

Implement one Characters style service and prompt renderer shared by Ongoing,
Storyline, and Timeline. It must:

- Load defaults or current settings for the exact ADR-defined scope.
- Validate and save all three controls atomically under an expected style revision.
- Resolve a complete, versioned instruction without provider-specific behavior.
- Copy the effective snapshot into each newly reserved response attempt and then
  into the completed persona message.
- Preserve the attempt snapshot if settings change while streaming.
- Resolve retries from the settings current at retry reservation time.

Replace hard-coded UI style constants only when the relevant mode is wired to the
service. Preserve historical Storyline scene and message snapshots during the
transition; do not rewrite applied migrations or old rows.

Test no-op and stale updates, defaults, all control combinations, stable Markdown
rendering instructions, a style update racing atomic input/attempt reservation,
updates during streaming, failure/retry, saved alternatives with different styles,
and restart.

Complete when the next newly reserved response in every Characters mode uses the
saved style and every historical persona message remains explainable by its own
snapshot.

### Slice 8 — Converse and summarize within an open Timeline day

Status: Complete

Extend Characters generation and branch-addressable summary services to Timeline
day targets. Reuse the durable pending/streaming/completed/failed/interrupted
attempt lifecycle, immutable message graph, expected-leaf guards, retry allowance,
and provider capability contracts.

For this slice, a response prompt may use only required identity/persona/start
facts, the effective style, a compatible summary for the current day, recent
selected-path messages from that day, and current input. Cross-day memory and
evolution state arrive in later slices. Never copy a prior day's transcript into
the current-day short-term window.

Run closure policy immediately before attempt reservation and persona-message
commit so a stream crossing the boundary follows the decision recorded in Slice 1.
Test incomplete-attempt recovery, summary compatibility after alternative
selection, no cross-day transcript leakage, style provenance, archive races, and
restart.

Complete when an open day supports durable generation and compatible summaries
without weakening Ongoing or Storyline behavior.

### Slice 9 — Add branch- and time-aware Timeline memory

Status: Complete

Generalize the existing Characters memory contracts only as far as required for a
Timeline temporal position. Preserve one continuity-owned logical lineage,
revision lifecycle, evidence, conflict handling, correction, exclusion,
reactivation, and hard deletion.

Implement Timeline extraction and response-memory selectors that require:

- Exact Timeline/day/conversation ownership.
- Selected source evidence and source persona checkpoint.
- Immutable occurrence and learned day positions no later than the target day.
- Current active, non-excluded content with branch-compatible evidence.
- A complete turn and one idempotent retryable effect per source persona message.
- Deterministic whole-record budgeting independent from response context budgeting.

The extraction snapshot may use eligible prior Timeline memory and current-day
selected history, but not another day transcript, another continuity, Storyline
memory, Ongoing state, or Chat memory. Corrections affect the next response without
changing historical prompts.

Add domain, repository, application, extraction-delta, management, branch-switch,
as-of, restart, and cross-mode isolation tests. Add an additive migration here only
if the Slice 1 decision proves the existing memory position representation cannot
safely support both scenes and days.

Complete when a later day can recall eligible selected evidence, an earlier day
cannot see future knowledge, and memory lifecycle operations remain continuity-
and mode-isolated.

### Slice 10 — Add Timeline relationship and persona evolution

Status: Complete

Prerequisite: the
[Continuity Entry structural refactor](../complete/CONTINUITY_ENTRY_REFACTOR_PLAN.md) is
complete. Extend its Entry-backed checkpoint evidence and relational Entry
ownership to Timeline. Use `ContinuityEntry` and `EntryPosition` for shared
ownership and temporal inputs, retaining Day vocabulary for calendar behavior and
UI. Ongoing keeps its distinct entryless evidence shape.

Make Timeline an eligible mode for the shared selector, snapshot, strategy,
validation, idempotent effect, event, projection, correction, and replay services.
Extend the explicit Entry history adapter for Timeline Day policies; preserve
Storyline selection behavior and Ongoing processing.
Use current-day selected messages as the new evidence window and allow eligible
prior Timeline memory and derived projections only under the policy recorded in
Slice 1.

Ensure that:

- Evolution requires exact owned Timeline Entry, conversation, adjacent source
  messages, and persona checkpoint; Entry position must not exceed the target
  position, and the checkpoint must belong to selected ancestry. It never uses a
  future day or unselected branch.
- Day closure does not erase already accepted events; later Entries use only
  evidence eligible from the settled selected ancestry.
- Selecting an open-day alternative rebuilds projections from eligible evidence.
- A failed inference remains retryable without rolling back the visible response.
- Corrections retain exact source Entry, message, checkpoint, and strategy
  provenance; relational Entry ownership remains validated during replay.
- Strategy and policy versions remain attached to effects and events.

Extend the native evaluation scenarios with day boundaries, offline gaps,
open-day alternative selection, and closure-frozen ancestry. Do not add
Timeline-only relationship dimensions or expose numeric scores.

Complete when Timeline evolution is conservative, replayable, temporally correct
through Entry positions and exact branch checkpoints, and unable to affect
another continuity or Chat. Timeline response-context insertion remains Slice 11.

Delivered with Timeline Entry-backed effects, exact selected checkpoint evidence,
current-day evidence selection, eligible prior-memory provenance, and projection
replay bounded by Entry position and checkpoint. The shared Entry history adapter
validates relational ownership and closure-frozen ancestry; inference commits
recheck selected Timeline sources. Open-day alternative selection rebuilds state,
failed inference remains retryable, and corrections preserve source and strategy
provenance. Ongoing and Storyline behavior remains covered by the existing suite.
No migration is required.

Coverage includes day boundaries, offline gaps, prior-memory provenance, future
relationship and adaptation exclusion, alternative selection, inference/selection
races, correction and restart, archive guards, contradictory persisted evidence,
native Timeline evaluation scenarios, and opt-in PostgreSQL duplicate-processing
coverage.

Validation: the full suite passed with 872 passed and 56 skipped; the final
focused evolution regression run passed all 21 tests. isort, Ruff, mypy, and diff
checks pass. Black exceeded its 30-second cap and was not rerun; its format check
remains incomplete. PostgreSQL verification requires
`CHARACTERS_TEST_DATABASE_URL`; provider smoke tests remain opt-in.

### Slice 11 — Assemble deterministic Timeline response context

Status: Complete

Implement the final Timeline response context in the accepted Characters order:

```text
Persona core
→ Identity
→ Relationship intent and user boundaries
→ Current relationship projection
→ Current persona adaptations
→ Eligible Timeline memory
→ Current-day state
→ Effective response style
→ Compatible current-day summary
→ Recent selected current-day messages
→ Current input
```

Keep mandatory ownership, persona, relationship, style, and input blocks distinct
from optional memory, summary, and history. Use deterministic whole-record
selection and the existing budget safety rules. Record selector and prompt-schema
versions with the attempt. Titles, other-day transcripts, future memory, excluded
records, unselected alternatives, and incomplete output must never enter the
prompt.

Test exact ordering, budget pressure, deterministic ties, Unicode, empty prior
history, prior-day memory, same-day summary compatibility, corrected memory,
evolution projections, and provider limits.

Complete when prompt assembly is deterministic and a Timeline response has the
required long-term continuity without transcript or temporal leakage.

Delivered with versioned deterministic Timeline prompt assembly in the accepted
block order, whole-record budget selection, current-day-only transcript and
summary inputs, branch- and time-eligible memory, and current evolution
projections. Attempt provenance records the Timeline selector and prompt-schema
versions. Focused coverage includes ordering, mandatory-capacity failure,
optional-budget pressure, Unicode, prior-day memory, and exclusion of the
Timeline title and other-day transcript.

### Slice 12 — Enforce latest-open-day graph actions and closed-history guards

Status: Complete

Complete Timeline graph policy:

- Only the latest open day permits retry, saved-future selection, and in-place
  Branch from here under the existing expected-leaf and retry-limit rules.
- A closed or non-latest day rejects input, continuation, completion, retry,
  selection, and Branch from here with a stable read-only reason.
- Missing, stale, foreign, or contradictory calendar facts fail closed.

Run closure policy before every graph action and serialize it with attempt,
selection, and completion writes. Preserve every saved node for inspection while
freezing the selected ancestry at closure. Add PostgreSQL race tests for retry,
selection, and Branch from here crossing the boundary, plus stale callers acting
on a formerly open day.

Complete when latest-open-day exploration is non-destructive, every historical
graph is permanently read-only, and no Timeline history-copy path exists.

Delivered with an injected-time Timeline write guard carried from closure policy
into attempt, streaming, completion, retry, selection, branching, and settings
transactions. Repository writes lock and revalidate exact Timeline/day ownership,
optimistic revision, latest Entry position, immutable boundary facts, and closure
state. Missing or contradictory facts fail closed with a stable reason. Timeline
Branch from here now resolves through the day adapter, open-day selection and
branching preserve every saved node, and graph inspection removes actions as soon
as due closure is observed.

Coverage includes open-day retry, selection, and non-destructive branching;
closed-day input and graph-action rejection; exact-boundary completion; stale and
non-latest callers; restart; evolution replay after path mutation; and opt-in
PostgreSQL races between closure and retry, selection, or Branch from here.

### Slice 13 — Ship Timeline creation, navigation, day, and archive UI

Status: Complete

Add focused Streamlit pages and composition wiring for:

- Reviewing identity, persona, and relationship before start without timezone
  setup.
- Confirming an idempotent new Timeline without creating its first day.
- Grouped active and archived Timeline navigation under identity and persona.
- Showing represented local dates, current/open/closed state, and empty-yet-valid
  Timeline state without an ongoing secondary clock.
- Archiving with confirmation and preserving read-only history.

Use application services only. Do not query SQLAlchemy, derive closure from the UI
process clock, or initialize Chat. Refresh and navigation must not create a day.

Add Streamlit tests for validation, duplicate submissions, DST boundary display,
offline closure on resume, no-interaction gaps, absence of timezone controls,
archive, and lazy area initialization.

Complete when a user can create, find, understand, resume, and archive a Timeline
without timezone setup or hidden calendar side effects.

Delivered with a dedicated reviewed Timeline start page, automatically captured
application-local IANA timezone, idempotent confirmation scope, and no day write
before first interaction. Focused navigation groups active and archived Timelines
under complete identity/persona ownership, represents only stored local dates,
distinguishes current-open, closed, and archived-read-only history, and explains a
valid Timeline with no represented days. Permanent archive requires explicit
confirmation and preserves the selected read-only history.

Production composition remains lazy and Characters-only. Timeline resume observes
an overdue latest-day closure through the injected clock, stored boundary facts,
selected graph path, and application/repository contracts before rendering; the UI
does not query persistence or consult its process clock. Coverage includes invalid
relationship input, revision-bound review, duplicate-submit prevention, absence of
timezone controls, DST-boundary dates, no-interaction gaps, empty navigation,
offline closure, archive confirmation, complete-scope validation, and Chat-free
shell routing.

### Slice 14 — Ship Timeline chat, style, memory, evolution, and history guidance UI

Status: Complete

Add the complete interaction surface:

- Send, stream, recover, retry, choose alternatives, and branch on an open day.
- Establish before Timeline start that previous days become read-only, distinguish
  the latest open day from closed history, and expose graph actions only on that
  open day.
- Explain at a closed message why retry, selection, and Branch from here are
  unavailable rather than presenting an action that fails late.
- Edit all three response-style controls, preview their effective meaning, save
  under a revision, and state that changes apply to the next response.
- Show each persona message's effective style alongside existing generation
  provenance without exposing raw internal prompt instructions by default.
- Reuse continuity-scoped memory and evolution inspection/correction components
  under Timeline eligibility and lifecycle rules.

Expose the same style controls on Ongoing and Storyline at the scope accepted in
Slice 1. Remove obsolete claims that a Storyline scene style is permanently fixed
if that is superseded by the decision; retain immutable historical message
snapshots.

Test widget isolation across pages and continuities, stale style revisions,
style-save/send ordering, retry under a changed style, exact-boundary closure,
closed-day action guidance, absence of historical graph actions, memory
management, evolution correction, and restart.

Complete when all Stage 8 behavior is usable through focused Characters pages and
the UI cannot bypass calendar, ownership, or revision guards.

Delivered with a shared continuity-scoped response-style editor on Ongoing,
Storyline, and Timeline. Its revision-bound controls preview the three effective
presentation choices, apply only to the next reserved response, and retain each
completed message's exact style controls and generation provenance without showing
raw prompt instructions. New Storyline scenes snapshot the current style at scene
creation instead of relying on the superseded fixed UI default.

Timeline now supports atomic first-day send, streaming and recovery, ordinary
same-day conversation, retry, alternative selection, and in-place branching
through the existing application guards. Creation and empty-history guidance make
clear that viewing creates no day and that prior days close permanently. Closed
messages explain why retry, selection, and branching are unavailable, and no
historical action is rendered. Timeline memory and relationship/persona evolution
reuse the continuity-scoped inspection and guarded correction surfaces with
day-aware provenance and archive behavior. Widget keys include complete continuity
or day ownership, and focused Streamlit coverage exercises style revisions and
scope isolation, atomic first send, closed-history guidance, derived-state panels,
and restart-safe service composition.

### Slice 15 — Add focused diagnostics and calendar recovery checks

Status: Complete

Add low-cardinality structured diagnostics for Timeline start, day creation,
closure observation, rejected historical operations, style revision, context
assembly, extraction/evolution terminal state, and recovery after interrupted
attempts. Include identifiers, mode, local date, boundary timezone,
policy/version, terminal reason, and latency where appropriate; do not log
conversation text, persona details, memory content, rendered style instructions,
or raw prompts. Keep any product analytics for attempted closed-message actions
privacy-conscious and separate from diagnostic content.

Add startup/read-path recovery checks that idempotently observe overdue closure
and incomplete attempts without scanning or mutating unrelated continuities. Keep
broad production observability, export, deletion, and extraction-readiness work in
Stage 9.

Complete when maintainers can distinguish calendar, style, generation, memory,
evolution, and historical-action failures without sensitive content or cross-area
coupling.

Delivered with a Characters-owned, allowlisted diagnostic event contract and a
structured logging adapter. Timeline start, represented-day reservation, closure,
historical write rejection, style revision, response-context selection,
post-response memory/evolution outcomes, and abandoned-attempt recovery now emit
stable identifiers, mode, calendar facts, policy versions, bounded terminal
reasons, aggregate context counts, and latency where measured. The event schema
cannot carry conversation text, persona details, memory content, rendered style
instructions, or raw prompts; no product analytics or Chat-area dependency was
introduced.

Timeline production composition shares the injected UTC clock and diagnostic sink
across navigation, first-day reservation, conversation policy, and recovery.
Resume observes an overdue latest-day closure and reconciles inactive attempts
only for the exact selected conversation. Recovery remains idempotent and does not
scan or mutate unrelated continuities. Focused coverage proves structured-log
allowlisting, style and closure outcomes, deterministic injected-time recovery,
and isolation from another continuity with an equally stale attempt.

### Slice 16 — Update project documents for shipped Stage 8 behavior

Status: Pending

Reserve this slice for project-document maintenance after the implementation and
UI behavior are final.

Update `README.md` with only shipped, user-visible behavior:

- Add Timeline to current Characters capabilities and the product model.
- Explain application-local day creation, missing days, permanent closure,
  latest-open-day branching, and response-style controls in concise product
  language.
- Extend the Characters quick-start flow with Timeline start/resume and style
  editing without duplicating the canonical setup path.
- Update local/cloud data-flow and configuration text only where the final code
  changes what is sent or exposes new operator settings.
- Verify every command, path, environment variable, default, model name, and
  privacy claim against the repository. Do not describe planned work as shipped.

Reconcile `DESIGN.md` with the accepted ADRs and final implementation, especially
Timeline ownership, day closure, captured local timezone, temporal memory/evolution,
open-day graph actions, context order, and message-boundary style behavior. Remove
superseded fixed-style statements, check nearby sections for contradictions, and
update its `Last updated` date for the material design change.

Mark Stage 8 complete in root `PLAN.md`, keep Stage 9 as the next stage, and update
`work/ongoing/TODO.md` without turning either file into release notes. Preserve the
stable README organization and the required DESIGN top-level section order.

Run:

```bash
git diff --check -- README.md DESIGN.md PLAN.md work/ongoing/TODO.md
```

Also verify relative links and any asserted commands or behavior. Broader code
checks remain Slice 17 work.

Complete when README accurately summarizes shipped Stage 8 behavior for users,
DESIGN and ADRs form one coherent contract, and project planning points to Stage 9.

### Slice 17 — Prove the Stage 8 milestone and area isolation

Status: Pending

Add one deterministic acceptance journey that:

1. Starts a Timeline with a reviewed relationship and automatically captured
   application-local timezone without creating a day or showing timezone controls.
2. Sends the first message atomically, streams a styled response, and verifies its
   local date, boundary facts, attempt, style, and provenance.
3. Changes style and proves the next response changes while the prior response does
   not; retries again under a later style and preserves both alternatives.
4. Crosses normal midnight and both DST transition shapes through the fake clock,
   including an offline gap, without placeholder days.
5. Changes the injected host zone after start and proves the Timeline's captured
   zone and all historical boundaries remain immutable.
6. Extracts and manages Timeline memory, evolves relationship/persona state, and
   proves prior knowledge is eligible only on valid selected later days.
7. Switches an open-day alternative and rebuilds derived state.
8. Rejects input, retry, selection, and in-place branching on a closed day.
9. Proves closed history exposes no Timeline fork, copy, or remapping path and
   explains unavailable actions without mutating history.
10. Restarts, resumes, archives, and proves the archived Timeline is read-only.

Run the complete Characters migration chain beside populated Chat data, exercise
real PostgreSQL constraints and concurrency tests, run deterministic evaluation
gates, and then run every CI-equivalent command listed above. Run optional local
Ollama smoke tests separately and do not count them as CI requirements.

Inspect the final diff for forbidden cross-area imports, schema references,
foreign keys, identifiers, queries, prompts, and runtime initialization. Confirm
Ongoing still has no long-term memory, Storyline temporal rules are unchanged,
all modes snapshot effective response style, and Chat remains unchanged. Record
any Black timeout or unavailable optional smoke dependency honestly.

Complete when closure, missing-day behavior, captured-zone stability, temporal
memory and evolution, latest-open-day graph rules, closed-history immutability, and
response-style controls are deterministic and tested across DST boundaries, and
the full required suite passes.

## Explicitly deferred

Keep the following outside Stage 8:

- Stage 9 repository-wide hardening, broad observability, export/deletion proof,
  and Characters extraction packaging.
- User-selected Timeline timezones, rezoning an existing Timeline, multiple
  concurrent Timeline timezones, or rewriting historical dates after travel.
- Persona-local clocks, inferred persona timezones, persona sleep or availability
  schedules, and automatic message restrictions based on persona location.
- Timezone detection from IP, browser geolocation, or persona/identity location;
  the pilot uses the local-first application runtime's injected IANA zone.
- Placeholder days, calendar streaks, synthetic missed-day summaries, reminders,
  scheduled persona messages, and background day creation.
- Timeline continuity forks, historical day reopening or rebasing, and moving
  memory/evolution between unrelated continuities.
- Continuing a closed Timeline moment in a new Storyline; evaluate that explicit
  mode transition only after observed behavior and privacy-conscious telemetry
  justify a context-transfer contract.
- Cross-area memory, prompts, identifiers, repositories, or data transfer.
- Model-generated style changes, automatic style optimization, arbitrary prompt
  injection through style controls, per-message editing of historical style, and
  provider-specific style vocabularies.
- Dialogue-format and tone controls, unsafe HTML rendering, or treating Markdown
  emphasis and layout as structured evidence.
- Learned memory ranking or new relationship scoring beyond the versioned
  strategies already accepted.
