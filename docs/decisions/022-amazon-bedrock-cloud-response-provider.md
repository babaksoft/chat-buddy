# ADR 022: Add Amazon Bedrock as Chat's next cloud response provider

- Status: Proposed
- Date: 2026-09-21
- Refines: ADRs 014, 015, and 017
- Follows: ADR 021

## Context

After proving Chat's provider-neutral response path with OpenAI, Chat needs a
second opt-in cloud provider without becoming a general AWS client. Amazon
Bedrock can expose several Claude capability and price tiers through one API,
but unrestricted model discovery, multiple authentication schemes, and exact
remote token counting would add unnecessary scope.

## Decision

Add a response-only provider with identifier `bedrock` and display name
`Amazon Bedrock`. Ollama remains the utility provider for titles, summaries,
and memory extraction. Use the synchronous Bedrock Runtime `Converse` and
`ConverseStream` operations with stateless, complete message lists. Do not add
tools, guardrails, prompt management, files, model customization, provisioned
throughput, or provider-side conversation state.

Expose a small, ordered allowlist containing one pinned Claude Haiku, Sonnet,
and Opus invocation target. Do not support Mistral, arbitrary model identifiers,
or live model discovery. Before this ADR is accepted, pin the exact versioned
model or inference-profile identifiers, region availability, context and output
limits, default reserves, and UI order. Persist the exact invocation target on
each generation attempt.

Reasoning remains outside the design. Send no Claude thinking or other
model-specific reasoning fields and expose no reasoning control. Translate only
Chat's supported text roles and common generation settings; reject `seed` and
any setting unsupported by the selected descriptor before invocation.

Bedrock is disabled unless `CHAT_BEDROCK_ENABLED=true`. Require an explicit
`CHAT_BEDROCK_REGION` and use the standard regional endpoint; do not support a
custom endpoint. Runtime inference uses a locally supplied Bedrock API key via
the AWS SDK's standard `AWS_BEARER_TOKEN_BEDROCK` environment variable. The
application does not create, refresh, or persist keys and does not silently fall
back to signed AWS credentials. Operators may use their current/default AWS
profile in `~/.aws/config` and `~/.aws/credentials` to obtain or administer the
key outside Chat Buddy; the application does not select named profiles or
perform IAM operations. Key lifetime and rotation policy must be settled before
acceptance.

Credentials must not enter descriptors, logs, exceptions, persistence,
Streamlit state, or UI. Missing configuration omits Bedrock without preventing
Ollama or OpenAI startup, and startup performs no network credential check.

Each Claude descriptor owns a conservative local token counter even when the
implementation is shared. The estimate includes Converse and message framing
overhead plus a documented safety margin. Runtime budgeting never calls AWS;
optional credential-gated tests may calibrate representative English,
multilingual, code, and long-message payloads against Bedrock `CountTokens`.
Apply ADR 017's prompt-capacity formula and an application prompt limit safely
below the selected model's provider limit so estimation error cannot routinely
produce oversized requests.

Normalize authentication, throttling, timeout, availability, rejected-request,
and invalid-response failures to ADR 021's safe provider error categories.
Streaming is not retried after output begins. Normal tests inject a mocked
Bedrock Runtime client and require neither a network nor an AWS account; an
optional, explicitly enabled smoke test is networked and billable.

The UI states that Bedrock calls are billable, sends eligible Chat context to
AWS and the selected model provider, and has reasoning features disabled. It
shows the configured region and, when applicable, that an inference profile may
route data across regions. Characters data is never eligible.

## Consequences

- Bedrock adds three curated Claude choices without changing Chat's application
  contracts or budgeting policy.
- Authentication, catalog management, and token counting remain deliberately
  local and bounded, at the cost of manual key rotation and model updates.
- Approximate counters require conservative margins and periodic calibration.
- Supporting signed credentials, additional model families, arbitrary regions,
  or reasoning later requires revising this decision.

## Alternatives considered

- Support both API keys and signed profile credentials in Chat Buddy — rejected
  initially because two credential paths and precedence rules add little value
  to the local proof.
- Add Mistral — rejected because it adds another tokenizer and model-specific
  prompt behavior without being necessary for useful model choice.
- Count every request remotely — rejected because budgeting makes repeated
  counts and must remain deterministic and usable offline.
- Discover the Bedrock catalog dynamically — rejected because availability,
  capabilities, limits, and data routing need reviewed, stable descriptors.

## References

- [Amazon Bedrock API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html)
- [Inference using the Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)
- [Amazon Bedrock CountTokens](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CountTokens.html)
- [Supported foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html)
