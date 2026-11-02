# ADR 039: Limit Timeline branching to the latest open day

- Status: Accepted
- Date: 2026-11-02
- Scope: Characters, Stage 8
- Supersedes: ADR 037's closed-day Timeline fork provisions
- Refines: ADRs 009, 011, and 037
- Consistent with: ADRs 008, 031, 032, 034, 035, and 036

## Context

Timeline represents relationship development through the user's actual local
calendar. A fork from an old closed day cannot continue naturally without either
reopening and backdating new interaction or moving immediately to the current
date. Reopening makes permanent day closure untrue. Moving to the current date can
insert a large real-time gap at the moment the user intended to explore an
alternate immediate future. Copying profiles, days, graphs, memories, and
evolution provenance does not resolve that semantic conflict.

Storyline does not have this problem because its scenes are narrative units rather
than fixed civil-time intervals.

## Decision

Timeline supports graph exploration only within its latest represented day while
that day is open and the Timeline is active. Retry, saved-future selection, and
Branch from here use the existing immutable message graph, expected-leaf guards,
and replay rules in place. Branch from here may name any exact owned completed
persona message in that writable day.

Once a day reaches its stored closing boundary, its selected path and all saved
alternatives become permanently read-only. A closed day rejects input,
continuation, completion, retry, alternative selection, and Branch from here. An
older day is also read-only even if contradictory supplied calendar facts claim it
is open. These operations return stable unavailable reasons; they do not return a
fork-required decision.

Timeline has no continuity-fork workflow. It does not duplicate profiles, copy
days or derived state, remap identifiers or provenance, or store fork source
metadata. Storyline fork behavior remains unchanged.

Memory, relationship, and persona-adaptation eligibility continue to follow the
selected ancestry. Switching an alternative or branching during the latest open
day rebuilds derived eligibility and projections under the existing replay rules.
Day closure freezes the selected ancestry; later days may use only state eligible
from that settled history.

The UI must establish this mode contract before Timeline start, distinguish the
latest open day from closed history, expose graph actions only where they are
valid, and explain locally why a historical action is unavailable. A possible
future action that continues a closed moment in a new Storyline is a mode
transition, not a Timeline branch, and is not part of this decision.

## Consequences

- Timeline preserves honest local-calendar dates and permanent day closure.
- Users must explore alternatives before the local day closes.
- Historical Timeline messages remain inspectable but cannot create alternate
  futures.
- Timeline persistence needs no profile duplication, fork provenance, bulk copy,
  or identifier-remapping workflow.
- Storyline remains the mode for revisiting alternate narrative paths after their
  original interaction window.

## Alternatives considered

- Copy a closed past into a new Timeline — rejected because neither inherited old
  dates nor an immediate jump to today's date matches the intended continuation.
- Reopen the source day and branch in place — rejected because it backdates new
  interaction and makes closure reversible.
- Rebase copied dates around the current date — rejected because it falsifies
  stored calendar facts, DST boundaries, and temporal provenance.
- Ship a closed-message transition into Storyline now — deferred until observed
  behavior and privacy-conscious telemetry justify a context-transfer contract.

## Behavioral examples

| Case | Given | When | Then |
|---|---|---|---|
| Open-day branch | The latest day is open and contains a completed persona message. | The user chooses Branch from here. | The next input branches in the same day without deleting the saved future. |
| Open-day selection | An open day has two completed persona alternatives. | The user selects the other alternative. | Current-day context and derived eligibility rebuild from its ancestry. |
| Closed-day action | Yesterday's day contains saved alternatives. | The user inspects a response after its closing boundary. | Retry, selection, and Branch from here are unavailable; history remains unchanged. |
| Offline closure | The application resumes after the latest day's boundary. | Closure is observed before a graph action. | Closure is persisted idempotently and the historical action is rejected. |
| New current day | The latest represented day is closed and today has no day yet. | The user sends a new input normally. | A new current-date day is created at the next position and inherits only eligible settled state. |
