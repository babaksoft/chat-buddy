# ADR 015: Use capability-specific Chat provider interfaces

- Status: Accepted
- Date: 2026-09-16
- Refines: ADR 014

## Context

ADR 014 establishes provider-neutral LLM access within each product area, but it
does not define how Chat discovers providers and models or how its different LLM
operations are separated.

The current Chat gateway combines response generation, title generation,
summarization, and memory extraction. A new response provider would therefore
have to implement unrelated utility operations before it could be used. Chat's
context configuration is also currently composed for one fixed model, even
though providers may expose different context limits, streaming support, and
generation parameters.

## Decision

Define separate Chat-owned protocols for response generation, title generation,
summarization, and memory extraction. A response-provider adapter is required to
implement only the response-generation capabilities it advertises. Utility
operations are routed independently and may continue to use a configured Ollama
adapter when another provider generates the visible response.

Add a Chat provider registry that exposes enabled providers and immutable model
descriptors. Each descriptor records a stable provider identifier, stable model
identifier, display name, context-window limit, streaming support, supported
generation parameters, defaults, and the token-estimation capability needed by
Chat context assembly. The registry validates a requested selection and produces
the effective non-secret generation configuration before generation begins.

Application services depend only on Chat-owned protocols and registry
abstractions. Provider SDK clients, authentication, endpoint configuration, and
translation to provider-specific request formats remain in Chat infrastructure.
The composition root registers adapters and model descriptors.

Persist stable identifiers rather than display names. Never place credentials,
authentication headers, endpoint secrets, or opaque client objects in model
descriptors or persisted generation configuration.

## Consequences

- A provider can be added for Chat responses without also implementing title,
  summary, or memory operations.
- Provider and model choices can be presented by the UI without importing a
  provider SDK.
- Context assembly can obtain model limits and token-estimation capabilities
  without hard-coding one model.
- The configured utility provider can differ from the provider selected for a
  visible response.
- Registry configuration and adapter composition must agree on stable provider
  and model identifiers.
- Capability differences must be validated before a provider request starts.

## Alternatives considered

- Keep one gateway protocol for every LLM operation — not selected because it
  makes each adapter implement unrelated capabilities and couples response
  selection to Chat utilities.
- Let the UI instantiate provider clients — not selected because it leaks
  authentication and infrastructure concerns into the presentation layer.
- Discover capabilities only by querying a live provider — not selected because
  Chat must remain testable and resumable when that provider is unavailable.

## Behavioral examples

- Selecting a registered Ollama model resolves an Ollama response adapter while
  title generation continues to use the independently configured utility route.
- Registering a test provider and model makes it selectable without changing the
  Chat application service.
- A model that does not support a requested generation parameter is rejected
  before a user message starts streaming.
