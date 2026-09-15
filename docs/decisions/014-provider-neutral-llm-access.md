# ADR 014: Use provider-neutral LLM access within each area

- Status: Accepted
- Date: 2026-09-15
- Supersedes: ADR 004

## Context

ADR 004 selected a locally installed Ollama service and rejected hosted LLM APIs
because the original product was limited to local inference. The Chat area now
needs persistent conversations with both local and cloud LLMs. Characters also
needs freedom to evaluate models without coupling its future standalone
application to Chat infrastructure.

## Decision

Each area defines and owns the LLM gateway protocols required by its application
services. Provider-specific adapters implement those contracts in the owning
area's infrastructure layer.

Retain a locally installed Ollama service as the initial local adapter. Permit
cloud-provider adapters and select each cloud vendor in a focused follow-up ADR
that records authentication, configuration, supported capabilities, and data
handling implications.

The application shell may share generic configuration, logging, HTTP transport,
and provider client utilities. It must not share area-specific gateway contracts,
prompt construction, context policy, or generation orchestration.

Record the effective provider, model, and generation configuration with generated
responses when the owning area's history and reproducibility rules require it.

## Consequences

- Application services can select local or cloud models without depending on a
  provider SDK.
- Ollama remains supported without defining the limits of the provider model.
- Chat and Characters may expose different providers and capabilities.
- Provider capability differences, credentials, and errors are normalized at
  each area's infrastructure boundary.
- Cloud integrations require explicit configuration and their own decision record
  before implementation.

## Alternatives considered

- Keep Ollama as the only provider — not selected because it does not meet Chat's
  cloud-model requirement.
- Share one application-level LLM gateway across both areas — not selected because
  it would couple their prompts, context policies, and future deployments.
- Add provider SDK calls directly to services — not selected because it violates
  the inward dependency rule and makes provider replacement difficult.

## Behavioral examples

- Chat can switch a conversation from an Ollama-backed model to a supported cloud
  model through Chat-owned application behavior.
- Characters can evaluate a model adapter without making that adapter available
  in Chat or importing a Chat service.
