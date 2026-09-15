# ADR 011: Use local calendar days with deterministic Timeline closure

- Status: Accepted
- Date: 2026-09-09
- Scope: Characters area; area boundary clarified by ADR 013

## Context

Timeline mode represents an ongoing relationship through calendar-day
conversations. It needs deterministic day boundaries that honor the identity's
local timezone and remain meaningful after timezone changes or offline periods.

## Decision

Store UTC timestamps and each conversation's resolved, immutable local date.
Each Timeline stores an IANA timezone and permits at most one conversation per
local date. The current local day is writable; after its local boundary passes it
is closed and read-only, including when closure is detected after the application
was offline. Timezone changes apply only to future boundaries.

## Consequences

- Days without interaction produce no conversation records.
- Closed days reject messages, retries, and in-place branches.
- An alternate past from a closed day requires a Timeline fork.
- A Clock abstraction and DST-aware tests are required when Timeline is built.

## Alternatives considered

- Use server UTC dates as the visible Timeline date — not selected because they
  do not represent the user's local-day experience.
- Keep historical local dates mutable after a timezone change — not selected
  because it would rewrite the Timeline's established history.

## Behavioral examples

- Opening the application after midnight closes the previous local day before
  allowing new interaction.
- A closed day remains viewable but cannot be retried or edited in place; a user
  forks the Timeline to explore an alternate version.
