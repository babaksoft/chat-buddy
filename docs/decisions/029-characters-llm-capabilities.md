# ADR 029: Resolve Characters model capabilities independently

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stage 4
- Refines: ADR 014

## Context

Characters needs visible persona responses and rolling summaries, but a provider
that can stream responses should not have to implement summarization. Characters
also cannot reuse Chat registries, gateway contracts, prompts, or context policy.

## Decision

Define separate Characters-owned contracts for streaming responses, summary
generation, token counting, and model resolution. A provider implements only the
capabilities it advertises; response and summary operations may resolve different
configured models and adapters.

Expose immutable model descriptors with stable provider and model identifiers,
context and output limits, supported capabilities and parameters, and non-secret
defaults. Resolve requested settings before persistence or provider invocation and
produce an immutable effective configuration with its input capacity after output
reservation. Reject unknown selections, unsupported capabilities or parameters,
and invalid budgets before calling a provider.

Application services assemble Characters prompts and depend only on these
contracts. SDK clients, endpoint details, error translation, and provider request
mapping remain in Characters infrastructure. Persist the effective provider,
model, configuration, capability, and budget with generated persona messages,
attempts, and summaries where they establish provenance. Credentials and client
objects never enter those snapshots.

Ollama remains the initial local adapter under ADR 014. Any Characters cloud
provider requires its own decision record before implementation.

## Consequences

- A response-only provider can be evaluated without implementing utility work.
- Summary configuration can change independently of visible response settings.
- Context assembly obtains capacity and token counting without provider SDK access.

## Alternatives considered

- Use one combined Characters gateway — rejected because it couples unrelated
  capabilities and prevents narrow provider substitution.
- Reuse Chat's registry and contracts — rejected because the areas own different
  prompts, context policy, configuration, and future deployment boundaries.
