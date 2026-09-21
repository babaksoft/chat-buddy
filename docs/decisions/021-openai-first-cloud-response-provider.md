# ADR 021: Use OpenAI as Chat's first cloud response provider

- Status: Accepted
- Date: 2026-09-21
- Last revised: 2026-09-21
- Refines: ADRs 014, 015, and 017

## Context

Chat needs opt-in cloud responses while remaining local-first. The first adapter
must satisfy the existing complete/streaming `ResponseGenerator` contract,
provide deterministic offline context budgeting, and leave title generation,
summarization, and memory extraction on Ollama. OpenAI, Anthropic, Gemini, and
Bedrock are viable; OpenAI's Responses API needs the least role, streaming, and
parameter translation for this contract. An installed dependency does not decide
the vendor.

## Decision

### Provider, models, and scope

Add one response-only provider with identifier `openai`, display name `OpenAI`,
and fixed endpoint `https://api.openai.com/v1/responses`. Do not support alternate
base URLs, Azure OpenAI, regional endpoints, provider tools, files, background
mode, conversations, `previous_response_id`, or provider-side compaction.

Register this curated model allowlist; never accept arbitrary model strings:

| Model identifier | UI role | Context | Max input | Max output | Default reserve |
|---|---|---:|---:|---:|---:|
| `gpt-5.6-terra` | Balanced; OpenAI default | 1,050,000 | 922,000 | 128,000 | 8,192 |
| `gpt-5.6-luna` | Economy/high volume | 1,050,000 | 922,000 | 128,000 | 8,192 |
| `gpt-5.6-sol` | Highest GPT-5.6 capability | 1,050,000 | 922,000 | 128,000 | 8,192 |
| `gpt-4.1-2025-04-14` | Explicitly non-reasoning baseline | 1,047,576 | context-bound | 32,768 | 4,096 |

Order Terra first so a user selecting OpenAI without a prior OpenAI choice gets
the balanced model. Do not register the moving `gpt-5.6` or `gpt-4.1` aliases.
Persist the exact selected identifier on every generation attempt.

Reasoning remains outside Stage 3. Send `reasoning.effort="none"` and
`reasoning.context="current_turn"` for every GPT-5.6 request; expose no reasoning
control and never use pro mode. GPT-4.1 needs no reasoning setting. The UI states
that OpenAI calls are billable and reasoning features are disabled; it need not
show volatile prices.

Use stateless Responses requests containing the complete assembled role/content
message list and `store=false`. Complete responses concatenate text and refusal
content in output order. Streams yield non-empty `response.output_text.delta`
and `response.refusal.delta` text in event order. Failed, cancelled, incomplete,
malformed, or empty terminal output is an invocation failure; partial stream text
follows ADR 016 and never becomes an assistant message.

### Configuration and secrets

OpenAI is disabled by default. Only `CHAT_OPENAI_ENABLED=true` opts in. Read the
key solely from `CHAT_OPENAI_API_KEY` and pass it explicitly to the SDK; never
fall back to `OPENAI_API_KEY`. Disabled configuration does not inspect the key.
Enabled configuration with a missing or blank key logs one secret-free warning,
omits OpenAI, and leaves Ollama usable. Do not validate credentials over the
network during startup.

Credentials and headers must never enter descriptors, persisted configuration,
attempts, logs, exceptions, fixtures, Streamlit state, or UI. Persist only the
provider/model identifiers and non-secret effective Chat configuration.

### Parameters and token budgeting

GPT-4.1 supports Chat's `temperature`, `top_p`, and `max_output_tokens` settings.
The GPT-5.6 models expose only `max_output_tokens` in Stage 3; their other Chat
sampling settings and `seed` are rejected before invocation. Omit unset request
parameters and reject output maxima above the selected model's limit.

Add immutable provider context, maximum-input, maximum-output, application
prompt-limit, output-reserve, and token-counter metadata to each descriptor. Set
the application prompt limit to 65,536 tokens for every OpenAI model so a
million-token provider window cannot postpone rolling summaries or create
unexpectedly large requests. ADR 017 becomes:

```text
prompt capacity = min(application prompt limit,
                      provider maximum input when present,
                      context window - output reserve)
                  - fixed prompt overhead
```

Use local `tiktoken` `o200k_base` counters with conservative Responses framing:
zero for no messages, otherwise
`16 + sum(16 + encoded(role) + encoded(content))`. Each descriptor owns a
counter even when implementations are shared. Runtime budgeting makes no cloud
token-count call. Mocked tests lock the formula; an optional credential-gated
test may compare representative payloads with OpenAI's exact input-token endpoint.

### Transport and failures

Use the official synchronous Python SDK with connect, pool, write, and inactivity
read timeouts of 5, 5, 30, and 120 seconds. Allow its two bounded retries for
non-streaming connection failures, HTTP 408/409/429 responses, and server errors.
Disable retries for streaming so emitted text is never replayed.

Normalize every SDK/provider failure to `ProviderInvocationError` with one safe
category:

| Failure | Category |
|---|---|
| Authentication or permission | `provider_authentication_failed` |
| Rate limit | `provider_rate_limited` |
| Connect or read timeout | `provider_timeout` |
| Connection or server error | `provider_unavailable` |
| Rejected request or model | `provider_request_rejected` |
| Invalid terminal response | `provider_invalid_response` |

Domain exceptions and logs exclude SDK bodies, headers, prompts, responses, and
chained SDK exceptions. Safe logs may contain category, status, request ID,
model ID, and duration. Application persistence keeps its generic provider-error
detail.

### Dependencies, tests, and data handling

Slice 10 adds `openai` and `tiktoken` only through
`uv add openai tiktoken`. Normal CI injects a mock client and has no network or
cloud-account requirement. Contract and composition tests cover all four model
descriptors, Terra defaulting, reasoning disabled, parameter validation,
complete/refusal output, ordered streaming, terminal states, safe errors,
timeouts/retries, disabled/missing-key startup, and secret non-disclosure.

An optional live smoke test runs only with `CHAT_OPENAI_SMOKE_TEST=true` and a
non-blank key; otherwise it is skipped. It is explicitly networked and billable.

Selecting OpenAI sends the assembled current input, recent turns, conversation
summary, and eligible Chat-wide memories to OpenAI; Characters data is never
eligible. OpenAI states API data is not used for training unless the customer
opts in. `store=false` avoids Responses application-state retention, while
default abuse-monitoring logs may retain customer content for up to 30 days.
Account-level Zero Data Retention or Modified Abuse Monitoring may alter that.
Local deletion cannot retract data already transmitted or retained by OpenAI.

## Consequences

- Ollama remains the default and the sole utility provider.
- Users get economy, balanced, higher-capability, and explicitly non-reasoning
  cloud choices through one adapter without reasoning features.
- Budgeting remains local, deterministic, model-specific, and capped far below
  provider windows; provider token counting is test-only.
- Cloud selection is billable and moves eligible Chat context off the machine.
- Other models, endpoints, cloud vendors, and reasoning controls require a later
  reviewed decision rather than free-form configuration.

## Alternatives considered

- Anthropic, Gemini, or Bedrock first — not selected because their initial
  authentication, role, region, or token-metadata boundary is broader.
- GPT-6 Astra — not selected because reasoning cannot be disabled.
- GPT-4.1 mini — not selected because Luna already fills the economy role while
  full GPT-4.1 provides a more distinct non-reasoning baseline.
- A generic OpenAI-compatible adapter, moving aliases, or arbitrary model IDs —
  not selected because authentication, limits, tokenization, capabilities, and
  data handling are not interchangeable or immutable.
- Cloud utility generation — not selected because this stage scopes OpenAI to
  visible responses and preserves local Ollama utilities.

## References

- [GPT-5.6 guide](https://developers.openai.com/api/docs/guides/latest-model/gpt-5.6)
- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), and [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [GPT-4.1 model metadata](https://developers.openai.com/api/docs/models/gpt-4.1)
- [Responses create API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Token counting](https://developers.openai.com/api/docs/guides/token-counting)
- [API data controls](https://developers.openai.com/api/docs/guides/your-data)
- [OpenAI Python SDK](https://github.com/openai/openai-python)
