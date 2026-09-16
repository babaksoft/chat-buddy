# Stage 2 Implementation Plan

Status: Frozen

Last updated: 2026-09-16

## Scope

Complete the provider-neutral Chat foundation described by Stage 2 of the main
execution plan. This stage owns provider and model selection, conversation and
message contracts, generation-attempt provenance and recovery, Ollama adaptation,
and the focused Chat UI needed to operate those capabilities.

Final summary and memory contracts, context eligibility and budgeting policy,
rolling-summary persistence, memory provenance and lifecycle, and the first cloud
adapter remain in Stage 3.

ADR 015 and ADR 016 are the accepted design constraints for this stage. Changing
their decisions or moving work across the Stage 2 and Stage 3 boundary requires
an explicit plan and ADR update before implementation continues. Implementation
details and task status may be recorded without changing the frozen scope.

## Slice sequence

Implement the slices in order. Each slice is a cohesive review unit and must keep
the application runnable. Run focused tests during a slice and the repository
quality checks before declaring the slice complete.

### Slice 1 — Accept the Stage 2 decisions

**Status: Complete.**

- Accept ADR 015, which separates response generation from Chat utility
  capabilities and defines the provider registry and model descriptors.
- Accept ADR 016, which defines immutable generation provenance, attempt states,
  incomplete-output handling, and retry semantics.
- Separate the Stage 2 provider and generation foundation from the Stage 3
  context, summary, and memory redesign in the main execution plan.

Acceptance:

- ADR 015 and ADR 016 have Accepted status.
- The main plan assigns final summary, memory, provenance, lifecycle, and context
  policy work only to Stage 3.
- This Stage 2 plan is frozen before implementation begins.

### Slice 2 — Introduce domain contracts

**Status: Planned.**

- Add immutable provider and model identifiers.
- Add model descriptors, supported capabilities, and generation configuration.
- Add generation-attempt records and lifecycle states.
- Split response generation, title generation, summarization, and memory
  extraction into capability-specific Chat-owned protocols.
- Add the Chat-owned provider registry and gateway-resolver protocols.
- Preserve existing behavior through temporary adapter-compatible interfaces
  where needed.

Acceptance:

- Domain contracts import no application, infrastructure, UI, or Characters
  modules.
- Invalid generation configurations and invalid attempt transitions are covered
  by focused unit tests.
- A fake response provider does not need to implement title, summary, or memory
  operations.

### Slice 3 — Adapt Ollama and build the provider registry

**Status: Planned.**

- Adapt Ollama to the new response-generation and utility interfaces.
- Add a configured registry containing the enabled Ollama provider and models.
- Validate model selection and supported generation parameters before invoking
  an adapter.
- Normalize provider failures into Chat-owned exceptions.
- Keep provider clients, endpoints, and authentication in infrastructure.
- Preserve existing synchronous and streaming Ollama behavior.

Acceptance:

- Existing Ollama adapter tests pass through the new interfaces.
- Registry tests cover lookup, defaults, unsupported models, and unsupported
  configuration.
- Application and UI modules do not import the Ollama SDK or adapter type.

### Slice 4 — Add generation persistence

**Status: Planned.**

- Add current provider, model, and requested generation defaults to a
  conversation.
- Add generation-attempt persistence with source user message, immutable
  effective configuration, lifecycle status, partial content, safe failure
  information, and timestamps.
- Link a completed attempt to its assistant message.
- Add transactional repository operations for starting an attempt, checkpointing
  it, completing it with an assistant message, and marking it failed or
  interrupted.
- Add a new Chat migration; do not modify the Stage 1 baseline.

Acceptance:

- Starting a user message and pending attempt is atomic.
- Completing an attempt and assistant message is atomic.
- Repository tests cover valid transitions and reject invalid transitions.
- Migration verification confirms that the Characters schema and version table
  are unchanged.

### Slice 5 — Route successful generation through the new lifecycle

**Status: Planned.**

- Resolve the selected model and response adapter through the registry.
- Validate requested configuration and snapshot the effective configuration
  before generation begins.
- Pass the selected model capabilities needed by the existing context builder
  without implementing the Stage 3 context-policy redesign.
- Stream the response and complete the attempt transactionally.
- Run title generation and existing completed-turn side effects only after the
  assistant message is committed.
- Make synchronous and streaming entry points use the same generation lifecycle.

Acceptance:

- New and resumed conversations stream successfully through the registry.
- Every completed assistant response has immutable attempt provenance.
- Changing the selected model affects the next attempt and does not rewrite prior
  provenance.
- Existing conversation behavior remains covered by application and integration
  tests.

### Slice 6 — Implement failure, interruption, and retry

**Status: Planned.**

- Mark provider errors as failed attempts and stream-consumer cancellation as
  interrupted attempts.
- Flush available partial content when an attempt terminates incompletely;
  periodic checkpoint frequency remains an infrastructure tuning choice.
- Keep incomplete output outside completed history and model context.
- Reconcile unresolved attempts that no longer have an active stream when their
  conversation resumes.
- Retry an incomplete attempt with a new attempt that reuses the original user
  message.
- Prevent title generation, memory extraction, and other completed-turn side
  effects for incomplete attempts.

Acceptance:

- Tests cover failure before output, failure after partial output, generator
  closure, stale-attempt reconciliation, failed retry, and successful retry.
- Retry does not duplicate the source user message.
- A successful retry produces exactly one new completed assistant message.
- No incomplete content is returned by normal conversation-history queries.

### Slice 7 — Add provider selection and recovery UI

**Status: Planned.**

- Add provider and model selectors whose choices come from the application
  service rather than infrastructure.
- Restore the persisted selection when a conversation resumes.
- Apply selection and configuration changes at the next generation boundary.
- Display failed and interrupted attempts without representing partial content as
  a completed assistant turn.
- Add a retry action for recoverable attempts.
- Keep the page focused on selection, history, generation, and recovery.

Acceptance:

- Streamlit tests cover new and resumed selection, model switching, successful
  streaming, failure, interruption, and retry.
- The UI does not resolve providers, instantiate adapters, or query repositories.
- Completed history renders as before when no failure occurs.

### Slice 8 — Prove provider extensibility and complete Stage 2

**Status: Planned.**

- Register a fake second provider through composition without changing Chat
  application services.
- Run common response-provider contract tests against mocked Ollama and the fake
  provider.
- Add or strengthen architecture checks for provider SDK isolation and area
  boundaries.
- Verify Chat migration ownership and Characters isolation.
- Run the complete repository quality suite.

Acceptance:

- The fake provider is selectable and can complete a streamed response without
  application-service changes.
- Ollama remains functional through the same provider-neutral contract.
- Chat and Characters retain import and schema isolation.
- `scripts/check.sh` passes.
- The Stage 2 completion criteria in the main execution plan are satisfied.
