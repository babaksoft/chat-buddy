# ADR 017: Separate Chat context eligibility from token budgeting

- Status: Accepted
- Date: 2026-09-18
- Refines: ADRs 015 and 016

## Context

The Chat prototype prepends every stored memory and counts the resulting messages
against one model window. Eligibility, token counting, and summarization are
combined in one context builder. This makes it unclear whether information is
absent because it is ineligible or because the selected model cannot fit it.

Stage 3 needs one deterministic context policy for synchronous generation,
streaming generation, and retry. It must account for model-specific limits,
reserve output capacity, exclude incomplete output, and fail before provider
invocation when mandatory input cannot fit.

## Decision

Use separate Chat application responsibilities for context eligibility and token
budgeting. Eligibility loads information that may be sent to the response
provider; budgeting chooses which eligible components fit the selected model.
Neither responsibility generates summaries, extracts memories, queries provider
SDKs, or performs persistence outside repository protocols.

Eligible components are:

- active Chat-wide memory as defined by ADR 019;
- the selected conversation's active summary as defined by ADR 018;
- complete turns not covered by that summary; and
- the current user input.

A complete turn is the source user message and assistant message linked by a
completed generation attempt. Pending, streaming, failed, and interrupted
attempts are ineligible. Partial output is never context. Completed turns are
ordered by assistant-message creation time with its identifier as a tie-breaker.

The current input is supplied separately to context assembly and appears exactly
once. Context is assembled and validated before a new user message and pending
attempt are persisted, or before a retry attempt is created. A context failure
therefore invokes no provider, adds no ordinary history, creates no new attempt,
and runs no completed-turn side effects.

Each model descriptor supplies a positive default output-token reserve in
addition to its context-window size and token counter. The request's effective
`max_output_tokens` is used when present; otherwise the model default is used.

```text
prompt capacity = context window - fixed prompt overhead - output reserve
summary trigger = floor(prompt capacity * summary trigger ratio)
```

All terms are non-negative and prompt capacity must be positive. The token
counter measures the final formatted `ChatMessage` list, including memory and
summary headers. Context assembly first checks whether the formatted current
input fits by itself. An oversized input is rejected before summarization or any
provider call.

Eligible components are selected in this priority order:

1. current user input;
2. active conversation summary, when present;
3. the configured minimum most-recent uncovered complete turns;
4. active Chat memories, ordered by current-revision update time descending and
   stable identifier ascending; and
5. additional uncovered complete turns, newest first.

The first three categories are mandatory when present. Optional items are added
greedily in stable priority order. An optional item that does not fit is skipped
as a whole, and later items may still be considered. Selected complete turns are
rendered chronologically. Final message order is memory system context, summary
system context, selected complete user/assistant pairs, then current input.

Context policy never truncates arbitrary memory, summary, or message text. If
mandatory formatted content cannot fit after an available summary update, Chat
raises a context-window error before creating an attempt or invoking the response
provider. A provider is never invoked above prompt capacity.

The trigger ratio, prompt overhead, minimum recent-turn count, and per-model
default output reserve are configurable tuning values. They may change while the
capacity formula, priority, whole-item behavior, and mandatory-content rule stay
the same. The initial summary trigger ratio remains `0.85`.

Additive budget metadata, stronger validation, provider-specific token counters,
and tuning changes are compatible updates when they preserve those invariants.
Changing mandatory context priority, admitting incomplete output, or crossing a
conversation or product-area boundary requires an ADR amendment or replacement.

## Consequences

- Eligibility decisions can be tested without a token counter or provider.
- Budgeting can be tested without repositories.
- Prompt capacity is conservative and model-specific.
- Some eligible memories or older turns may be omitted.
- Mandatory content fails visibly instead of being silently truncated.
- Provider selection can change the context result without changing eligibility.

## Alternatives considered

- Keep eligibility and counting in one context builder — not selected because it
  couples repository policy to model limits and summary generation.
- Inject all active memories before checking capacity — not selected because
  optional memory could crowd out mandatory conversation context.
- Truncate text to make it fit — not selected because arbitrary truncation can
  corrupt meaning and makes provenance misleading.
- Use one global token limit — not selected because registered models have
  different context windows, output limits, and tokenizers.

## Behavioral examples

- An active memory may be eligible but omitted when the selected model lacks
  room after mandatory conversation context.
- Failed partial output is excluded from both a normal generation and its retry.
- Switching to a smaller model can trigger summary recompaction under ADR 018.
- If the current input alone exceeds prompt capacity, Chat creates no attempt and
  calls neither the summary nor response provider.
