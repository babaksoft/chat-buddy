# Stage 7 Execution Plan — Relationship and Persona Evolution

Status: In progress

Last updated: 2026-10-30

## Outcome

Add explainable, continuity-scoped relationship evolution and persona adaptation
to Characters.

After an eligible completed turn, a versioned strategy may propose a bounded set
of typed changes. The application validates the proposal against immutable
ownership, selected evidence, user intent, boundaries, transition rules, and
conservative evidence thresholds. Accepted changes become append-only events from
which current relationship and adaptation projections can be rebuilt.

Evolution must remain:

- Isolated to one Characters continuity.
- Traceable to exact selected evidence.
- Correct after retry selection, branching, correction, and Storyline forks.
- Unable to modify the authored persona core or user-controlled boundaries.
- Replaceable and measurable through versioned strategies and evaluation
  scenarios.
- Independent of Chat.

## Evaluation approach

Use an in-repository evaluation harness as the authoritative foundation. It should
run deterministically under pytest, require no network service, and represent
evolution-specific concepts directly.

Phoenix is the best initial optional integration because it is already a project
dependency in [pyproject.toml](../../pyproject.toml), supports local datasets,
experiments, tracing, deterministic evaluators, and LLM judges, and can be
self-hosted. Its documentation recommends beginning with manually curated
examples, which suits Stage 7 well. [Phoenix datasets](https://arize.com/docs/phoenix/learn/datasets-and-experiments/datasets-concepts),
[Phoenix evaluation](https://arize.com/docs/phoenix/evaluation/llm-evals/evaluator-traces).

Do not initially add Ragas or TruLens:

- Ragas supports custom and rubric-based metrics, but many built-in metrics target
  RAG and agent workflows rather than typed state transitions.
  [Ragas metrics](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/)
- TruLens supports custom deterministic and model-based metrics and recommends
  beginning with domain-expert evaluations, but adding it now would overlap with
  the native harness and existing Phoenix dependency.
  [TruLens feedback functions](https://www.trulens.org/getting_started/core_concepts/feedback_functions/)

Keep the evaluation runner independent of Phoenix so another framework can be
added through an adapter later.

## Baseline contract

### Stable domain rules

The following are product invariants, not experimental strategy behavior:

- Persona core never evolves.
- Factual knowledge belongs to memory, not persona adaptation.
- Persona adaptation describes continuity-specific behavior toward the identity.
- User-selected boundaries cannot be automatically removed or weakened.
- Evolution uses only evidence eligible for the current continuity and selected
  history.
- Rolling summaries may aid interpretation but cannot serve as final provenance.
- Platonic intent cannot produce romantic evolution.
- Major romantic transitions require explicit narrative evidence.
- Every applied change cites exact source evidence.
- Evolution is idempotent per source persona checkpoint.
- Archived continuities cannot evolve.
- Projections are rebuildable and are not the source of truth.

### Experimental surfaces

Experiments may replace or configure:

- Evolution evidence selection.
- Proposal prompt and provider.
- Proposal strategy implementation.
- Conservative thresholds for gradual changes.
- Accepted persona-adaptation facets.
- Evaluation rubrics and optional model judges.

Every experiment records exact selector, strategy, policy, prompt-schema,
provider, and model versions.

### Simple baseline thresholds

The initial policy should be understandable rather than statistically
sophisticated:

- A current interaction dynamic may change from one strong explicit exchange.
- Trust, affection, and social status require compatible evidence from at least
  two distinct turns.
- Romantic interest requires explicit evidence and compatible relationship
  intent.
- Partnership, engagement, marriage, breakup, and reconciliation require an
  explicit unambiguous narrative event.
- Temporary conflict affects the dynamic before it affects durable status.
- Reversing a gradual change requires later opposing evidence under the same
  conservative threshold.
- Uncertainty produces no change.

These are versioned calibration rules, not permanent universal constants.

## Evaluation model

Create a framework-neutral `EvolutionScenario` containing:

- Scenario name and behavioral tags.
- Starting relationship and current projection.
- Current persona adaptations.
- User intent and boundaries.
- Eligible evidence in chronological order.
- Exact new source turn.
- Required proposals.
- Permitted proposals.
- Forbidden proposals.
- Expected application decision and reason.
- Expected relationship and adaptation projections after replay.

Initial deterministic metrics:

- Schema validity.
- Ownership and evidence validity.
- Required-proposal recall.
- Forbidden-proposal rate.
- Hard-invariant violation rate.
- No-change correctness.
- Policy acceptance or rejection correctness.
- Projection replay correctness.
- Branch and fork correctness.
- Correction correctness.
- Duplicate-effect rate.
- State-oscillation scenarios.

Hard-invariant, idempotency, and replay metrics must pass exactly. Qualitative
strategy metrics may be comparative rather than absolute.

## Slice sequence

| Slice | Self-contained outcome | Depends on | Database impact |
|---|---|---:|---|
| 1 | Establish terminology, invariants, and experiment boundaries | Stage 6 | None |
| 2 | Add typed evolution state, evidence, proposal, and event values | 1 | None |
| 3 | Add the native scenario and evaluation harness | 1–2 | None |
| 4 | Define replaceable selector, strategy, and policy seams | 2–3 | None |
| 5 | Persist effects, decisions, events, and projections | 2–4 | Characters migration |
| 6 | Build immutable, budgeted evolution snapshots | 4–5 | Existing repository operations |
| 7 | Validate typed proposals and baseline transitions | 3, 6 | None |
| 8 | Apply evolution idempotently after eligible turns | 5–7 | Existing evolution records |
| 9 | Rebuild projections and support user corrections | 5–8 | Existing evolution records |
| 10 | Implement the baseline proposal strategy | 3–9 | None |
| 11 | Add evolution state to subsequent response context | 8–10 | None |
| 12 | Rebuild evolution after retry selection and in-place branching | 9–11 | Existing evolution records |
| 13 | Preserve eligible evolution through Storyline forks | 9, 12 | Existing evolution records |
| 14 | Add inspection and correction UI | 9–13 | Existing evolution records |
| 15 | Add focused observability and optional Phoenix integration | 3, 8–14 | None |
| 16 | Update project documents for delivered evolution behavior | 1–15 | None |
| 17 | Prove the milestone | 1–16 | Verification only |

## Slice details

### Slice 1 — Record terminology and durable decisions

Status: Complete

Revise or supersede ADR 010 and add only the ADRs needed to establish:

- Relationship state versus persona adaptation versus current state.
- Memory versus adaptation ownership.
- Evidence, proposal, decision, event, effect, and projection terminology.
- User boundaries as constraints rather than inferred relationship dimensions.
- Model-proposed/application-validated evolution.
- Append-only events and rebuildable projections.
- Stable invariants versus versioned experimental policy.

Include concise behavioral examples for friendship, romance, conflict, adaptation,
correction, branch selection, and fresh continuities.

Seed the first evaluation scenario inventory directly from the ADR examples.

Complete when the vocabulary is unambiguous and every later slice can refer to one
accepted definition.

### Slice 2 — Add executable evolution values

Status: Complete

Replace the current string-oriented proposal scaffold with frozen Pydantic values
for:

- `RelationshipProjection`.
- `PersonaAdaptationProjection`.
- `EvolutionEvidenceReference`.
- `EvolutionSnapshot`.
- Typed relationship-change commands.
- Relationship milestone commands.
- Persona-adaptation commands.
- Bounded atomic `EvolutionProposal`.
- `EvolutionEvent`.
- `EvolutionDecision`.
- Strategy and policy provenance.

Use exact enums for relationship values. Establish a small initial
adaptation-facet vocabulary such as communication style, openness, support style,
conflict style, and shared habit.

Evolution evidence must support Ongoing turns and Storyline scene/conversation
checkpoints without pretending that one Storyline has only one conversation.

Complete when invalid values, foreign evidence, duplicate sources, malformed
transitions, and unbounded proposals fail at the domain boundary.

### Slice 3 — Ship the native evaluation harness

Status: Complete

Add a development-only evaluation area, preferably `evaluations/characters/`,
with:

- Versioned JSONL scenario datasets.
- Pydantic dataset loading and validation.
- A deterministic runner accepting any evolution strategy and policy.
- Per-scenario results and aggregate metrics.
- Machine-readable JSON output and concise terminal output.
- Pytest integration for promotion gates.

Start with curated scenarios covering:

- Platonic warmth without romance.
- Gradual trust and friendship.
- Insufficient evidence.
- Explicit partnership and engagement.
- Vague sentiment rejected as a milestone.
- Temporary conflict without relationship erasure.
- User boundary enforcement.
- Persona-core contradiction.
- Adaptation versus memory classification.
- Retry selection and replay.
- Correction and fresh-continuity isolation.

Complete when the existing no-change strategy and test strategies can be compared
using the same dataset without a database, provider, or Phoenix instance.

### Slice 4 — Define the replaceable evolution seams

Status: Complete

Introduce narrow Characters-owned protocols for:

- Selecting an immutable evolution snapshot.
- Producing a typed proposal.
- Applying versioned gradual-change thresholds.
- Reporting experiment results.

Keep hard domain validation outside replaceable strategies and policies.

Define an `EvolutionConfiguration` carrying selector, strategy, threshold-policy,
and schema identities. Resolve it at a message boundary and record it on each
effect. Experimental assignment should be continuity-stable unless explicitly
changed.

Provide:

- A no-change production strategy.
- A deterministic fixture strategy.
- A strict baseline threshold policy.
- A no-op experiment reporter.

Complete when strategies and policies can be substituted independently without
repository, SDK, or Chat dependencies.

### Slice 5 — Persist evolution history and projections

Status: Complete

Add a Characters migration and repositories for:

- One evolution effect per source persona checkpoint.
- Terminal decision and bounded proposal audit data.
- Append-only evolution events.
- Current relationship projection.
- Current persona-adaptation projection.
- Projection revision and rebuild checkpoint.

Use an effect lifecycle such as:

```text
reserved → no_change | applied | rejected
```

Store strategy, selector, policy, prompt schema, provider, model, source
checkpoint, timestamps, and rejection reason. Commit accepted events and their
updated projections atomically.

Projections remain caches; events and corrections remain authoritative.

Complete when repository contract, migration, concurrency, and restart tests prove
idempotency and projection consistency.

### Slice 6 — Build evolution snapshots

Status: Complete

Create a dedicated-budget selector that assembles:

1. Identity and persona core.
2. Relationship intent and user boundaries.
3. Current relationship projection.
4. Current persona adaptations.
5. Relevant continuity memory where eligible.
6. Compatible summary as interpretation context.
7. Recent selected-path turns.
8. Exact new turn marked as new evidence.

Optional context must never displace ownership, current state, boundaries, or the
new turn. Summaries cannot be cited as evidence. Memory-supported proposals must
ultimately retain their original turn provenance.

Complete when snapshots are deterministic, bounded, continuity-safe, branch-aware,
and usable across Storyline scenes.

### Slice 7 — Implement validation and transition policy

Status: Complete

Validate proposals against:

- Expected current projection revision and values.
- Relationship intent.
- User boundaries.
- Allowed transition graphs.
- Evidence eligibility.
- Explicit milestone requirements.
- Baseline gradual-change thresholds.
- Persona-core compatibility.
- Adaptation-facet policy.
- Proposal size limits.

Treat one proposal as an atomic change set: apply all validated commands or reject
the proposal with a stable reason code.

Add every validator outcome to the evaluation harness.

Complete when arbitrary strategy output cannot bypass product invariants and all
rejection reasons are deterministic.

### Slice 8 — Orchestrate idempotent evolution effects

Status: Complete

After a complete selected persona turn:

1. Reserve or resume its evolution effect.
2. Build the immutable snapshot.
3. Invoke the configured strategy.
4. Validate the proposal.
5. Persist no-change, rejection, or accepted events and projections.
6. Leave failures retryable without rolling back the visible response.

Do not run evolution for incomplete output, unmatched user input, unselected
history, or archived continuities.

Complete when repeated, concurrent, failed, and restarted processing cannot
duplicate an event or lose a committed response.

### Slice 9 — Rebuild projections and support corrections

Status: Complete

Implement deterministic replay from:

- Starting relationship.
- Eligible inferred events.
- User-authored corrections.
- Event exclusions or replacements.

A correction appends a user-authored event; it does not edit the original event or
conversation. Rebuild dependent later state rather than patching only the visible
projection.

Support:

- Correcting an inferred value.
- Excluding an erroneous event.
- Replacing a persona adaptation.
- Restoring an excluded interpretation when valid.
- Optimistic projection revision checks.

Complete when projection deletion and full replay produce exactly the same state
as incremental application.

### Slice 10 — Implement the baseline strategy

Status: Complete

Add a provider-backed baseline strategy that:

- Receives only the immutable snapshot.
- Produces bounded typed output.
- Treats prior context as interpretation support.
- Requires the new source turn to support or explicitly confirm each proposal.
- Returns no change when evidence is ambiguous.
- Cannot write persistence directly.

Use a deterministic fake provider for ordinary tests and an explicitly enabled
Ollama smoke evaluation for local qualitative inspection.

Run the complete curated dataset before promoting the baseline from no-change.

Complete when the baseline meets all hard gates and records its exact prompt,
schema, provider, and model provenance.

### Slice 11 — Feed projections into future responses

Status: Complete

Update Characters context assembly to use:

```text
Persona core
→ Identity
→ Relationship intent and user boundaries
→ Current relationship projection
→ Current persona adaptations
→ Eligible memory
→ Scene/current state
→ Response style
→ Summary and recent selected messages
```

Keep adaptation concise and budgeted. Never render rejected proposals, excluded
events, experiment metadata, or hidden numeric scores into the persona prompt.

Complete when an accepted or corrected event affects the next response context
without rewriting prior prompts.

### Slice 12 — Rebuild after retry selection and branching

When an alternative becomes selected:

- Recompute eligible events from selected ancestry.
- Rebuild both projections.
- Preserve events supported by still-selected evidence.
- Make deselected events inactive without deleting them.
- Restore them if their supporting history becomes selected again.

Ongoing and writable Storyline branches remain in place. The evolution result must
agree with a clean replay of the newly selected path.

Complete when branch switching cannot leave stale relationship or adaptation state
in context.

### Slice 13 — Preserve evolution through Storyline forks

Extend the reviewed Storyline fork to:

- Copy only evolution events supported by copied histories.
- Remap evidence, effect, event, and projection identifiers.
- Exclude later or off-path events.
- Rebuild target projections from copied starting state and events.
- Share no mutable or continuity-owned row.
- Leave the source unchanged.

A fresh Storyline start remains independent and copies no evolution.

Complete when original and fork can evolve independently from the exact branch
point.

### Slice 14 — Add inspection and correction UI

Show qualitative state rather than progress bars:

- Current relationship dimensions.
- Active persona adaptations.
- Milestones.
- Exact evidence and rationale.
- Strategy and policy versions in diagnostic detail.
- Rejected proposals only in an optional diagnostic view.
- Correction and exclusion actions with confirmation.

Clearly distinguish:

- User-selected starting state.
- Inferred evolution.
- User-authored correction.
- Temporarily inactive branch-derived state.

Complete when users can understand why state exists and correct it without editing
conversation history.

### Slice 15 — Add observability and experiment reporting

Add low-cardinality structured logs and metrics for:

- Effect terminal state.
- Proposal command counts.
- Acceptance and rejection reasons.
- Strategy, selector, and policy versions.
- Snapshot and strategy latency.
- Projection rebuild reason and duration.
- Correction count.
- Duplicate reservation conflicts.

Do not log conversation text or persona details by default.

Add an optional Phoenix adapter that can:

- Publish curated datasets.
- Record experiment runs.
- Attach deterministic evaluation metrics.
- Trace selector, strategy, validation, and application spans.
- Remain disabled without changing behavior.

Do not make Phoenix, Ragas, TruLens, a cloud service, or an evaluator model
necessary for application startup or CI.

Complete when maintainers can compare two strategies locally while the ordinary
application and test suite remain independent of the observability backend.

### Slice 16 — Update project documents for delivered evolution behavior

Update `README.md` only for shipped user-visible relationship evolution, persona
adaptation, correction, configuration, privacy, or data-flow behavior. Describe
qualitative state and provenance without exposing internal class, table, strategy,
or evaluation details.

Reconcile `DESIGN.md` with the accepted ADRs and final delivered behavior, including
the relationship/adaptation/current-state distinction, evidence and projection
rules, context order, correction, branching, Storyline forks, and experiment
boundaries. Update its `Last updated` date and remove superseded statements.

Mark Stage 7 complete in root `PLAN.md`, keep Stage 8 as the next delivery stage,
and update `work/ongoing/TODO.md` without turning either document into a release
log. Keep delivery mechanics and detailed verification in this stage plan.

Run `git diff --check -- README.md DESIGN.md PLAN.md work/ongoing/TODO.md` and
relevant documentation/link checks. Broader code checks remain Slice 17 work.

Complete when README describes only shipped behavior, DESIGN is coherent with the
accepted decisions, and project planning points to the next stage.

### Slice 17 — Prove the Stage 7 milestone

Add one acceptance journey covering:

- Natural and platonic starts.
- Gradual friendship and trust.
- Explicit romantic milestones.
- Rejected boundary conflicts.
- Persona adaptation without core mutation.
- Failed and retried evolution effects.
- User correction.
- Retry-alternative selection.
- Ongoing in-place branching.
- Storyline fork remapping.
- Archive and fresh independent continuity.
- Restart and projection replay.
- Strategy comparison through the evaluation runner.

Run all CI-equivalent checks, Characters migration/concurrency tests,
deterministic evaluation gates, and optional local Ollama/Phoenix smoke workflows
separately.

Complete when relationship and adaptation state is explainable, replayable,
branch-correct, correction-safe, experimentally replaceable, and has no Chat
dependency or effect.

## Explicitly deferred

Keep these outside the baseline:

- Learned or embedding-based evidence selection.
- Numeric relationship scores exposed as product state.
- Model-generated boundary removal.
- Automatic persona-core evolution.
- Cross-continuity learning outside reviewed forks.
- Online self-optimizing strategies.
- Automatic strategy promotion.
- Production shadow evaluation of every turn.
- Synthetic scenario generation at scale.
- Ragas or TruLens integration unless the native/Phoenix approach proves
  insufficient.
- Statistical confidence or salience models.
- Timeline-specific evolution eligibility, which belongs with Stage 8.
