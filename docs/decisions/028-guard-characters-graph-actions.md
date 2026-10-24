# ADR 028: Guard retries, selections, and in-place branches

- Status: Accepted
- Date: 2026-10-24
- Scope: Characters, Stage 5
- Refines: ADRs 009 and 024

## Context

ADR 009 defines the immutable conversation graph and retry allowance. The shipped
Stage 5 workflows also need one durable action boundary so stale UI events, late
provider output, and concurrent graph changes cannot select or create the wrong
future.

## Decision

Keep initial generation, incomplete-turn continuation, completed-response retry,
alternative selection, and branch-from-here as distinct operations. Every action
uses the complete identity, persona, continuity, and conversation scope. Writes
require an active continuity, no other open attempt, and the selected leaf observed
by the caller. Mode authorization runs before mutation and fails closed as defined
by ADR 009.

Incomplete continuation applies only to an existing unmatched user node. It starts
a new attempt for that input, preserves earlier failed or interrupted attempts,
and is not a completed-response retry.

A completed-response retry applies only to the selected final persona node. It
uses that node's parent user message with the current effective response settings;
the replaced response and its siblings are absent from the retry prompt. A
successful retry adds and selects a persona sibling. One initial response plus
three successful retries is the limit. Failed and interrupted attempts add no
message, preserve selection, and consume no retry allowance.

Alternative selection names an exact owned off-path persona leaf. A saved future
with descendants must be selected by its exact leaf; the application does not
guess among descendants. Branch-from-here names an older persona node on the
selected ancestry, selects that node, and lets the next send create a new user
child. Selecting the current leaf, branching from an off-path node, or using a
foreign, ambiguous, or stale target is rejected. Neither operation deletes prior
nodes, attempts, summaries, or provenance.

Provider calls remain outside transactions. Attempt reservation records the
effective generation snapshot and selected-leaf guard. Completion rechecks
ownership, continuity writability, selected leaf, open-attempt state, and retry
capacity before atomically adding and selecting a persona node. Output that loses
one of those races remains failed or interrupted attempt evidence and never enters
committed history.

Graph inspection may show all alternatives, but normal history, context,
summarization, and later derivation use only the selected root-to-leaf ancestry.

## Consequences

- Replayed or concurrent actions cannot silently replace a newer selection.
- Retry failures are recoverable without consuming the user's bounded allowance.
- Divergent Ongoing futures remain durable and can be selected after restart.

## Alternatives considered

- Treat continuation and retry as one action — rejected because an incomplete turn
  has no committed persona response to replace.
- Infer a saved descendant from an interior node — rejected because multiple
  futures can exist and the choice would be ambiguous.
