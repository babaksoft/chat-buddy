# ADR 011: Use immutable application-local day boundaries for Timeline

- Status: Accepted
- Date: 2026-09-09
- Last revised: 2026-11-02
- Scope: Characters area; area boundary clarified by ADR 013
- Refined by: ADR 037

## Context

Timeline represents an ongoing relationship through local-calendar-day
conversations. Day identity and writability must remain deterministic across
daylight-saving transitions, offline periods, and concurrent requests without
making users configure or remember a separate role-playing timezone.

A persona's authored location may differ from the user's location. Treating that
location as Timeline calendar policy would make ordinary interaction depend on a
hidden second clock and would conflate persona context with continuity ownership.

## Decision

Use an injected clock that supplies an aware UTC instant and an injected local-zone
source that supplies the application's current valid IANA timezone. Starting a
Timeline automatically captures that application-local zone as its immutable
calendar timezone. It is internal calendar provenance: the user does not select,
review, or change it, and identity or persona timezone metadata does not override
it.

A represented day owns:

- An immutable positive position unique within its Timeline.
- An immutable local date, boundary timezone, UTC opening instant, and UTC closing
  boundary.
- One conversation graph and its branch-addressable summary lineage.
- Its exact message, memory, relationship, and adaptation provenance.

Resolve every day in the Timeline's captured calendar timezone. The opening
boundary is the earliest UTC instant that maps into that local date, and the
closing boundary is the earliest later UTC instant that maps into the next locally
representable date. For an ambiguous boundary choose the earlier instant; for a
nonexistent local midnight advance to the first valid instant of that date. This
makes a represented day 23, 24, 25, or another historically correct number of
hours without inventing or duplicating local time. A skipped civil date cannot be
represented.

Create a day only when reserving its first user message and pending response
attempt. Day creation, message creation, attempt reservation, position allocation,
and the selected-leaf guard commit in one transaction under the Timeline lock.
Opening, refreshing, or navigating Timeline creates nothing. Offline gaps create
no placeholders; the next interaction may therefore advance by several local
dates while its position advances by exactly one.

A day is open only while the injected current instant is earlier than its stored
closing boundary and the Timeline is active. Once the instant reaches or passes
that boundary, observing the day persists closure idempotently. A closed day is
read-only: it rejects new input, incomplete continuation, completion of an open
attempt, completed-response retry, alternative selection, and in-place branching.
An open attempt that loses the boundary race becomes interrupted evidence and
does not produce a persona message.

Represented local dates increase strictly with position in the immutable calendar
timezone. Changing the host or device timezone later does not rename, reopen, or
rezone the Timeline or any represented day. A different calendar timezone requires
a fresh Timeline rather than mutation of an existing continuity.

Persona-local clocks, inferred persona timezones, sleep or availability policy,
and automatic message restrictions based on persona location are outside Timeline
calendar behavior. They may be introduced later as optional presentation features
without changing day ownership or closure.

## Consequences

- Timeline follows the user's application-local calendar without timezone setup.
- Days without interaction produce no day, conversation, or summary records.
- Historical day identity remains stable through tzdata updates and host-timezone
  changes.
- Calendar decisions can be tested with aware UTC instants and injected named
  zones without changing the test process timezone or waiting for wall-clock time.
- Boundary observation and first-send reservation serialize on the Timeline
  revision and return explicit stale or closed results.
- Exploring an alternate past from a closed day uses ADR 037's reviewed Timeline
  fork rather than changing the source.

## Alternatives considered

- Let users select and later change a Timeline timezone — rejected because it
  introduces persistent clock UI, travel transitions, calendar catch-up, and
  surprising closure behavior for a secondary pilot concern.
- Derive Timeline time from identity or persona location — rejected because the
  user's calendar and a character's fictional local time are different concepts.
- Use server UTC dates as visible Timeline dates — rejected because they do not
  represent the local-first user's calendar-day experience.
- Let an attempt complete after closure — rejected because closure would no longer
  be a permanent read-only boundary.

## Behavioral examples

The examples use injected instants and zones; each operation is deterministic and
suitable for an application or repository test.

| Case | Given | When | Then |
|---|---|---|---|
| Start | The application-local zone is `Asia/Tehran`. | The user confirms a Timeline after reviewing profiles and relationship state. | The Timeline captures `Asia/Tehran` without showing a timezone field and creates no day. |
| First interaction | The captured zone is `Asia/Tehran`, the Timeline has no days, and the clock is `2026-11-02T08:00:00Z`. | The first send is reserved. | Position 1, local date `2026-11-02`, boundaries `2026-11-01T20:30:00Z` and `2026-11-02T20:30:00Z`, one user node, and one pending attempt commit together. |
| No interaction | The Timeline is opened on `2026-11-03` and `2026-11-04`. | The user only navigates and refreshes. | No day is created and no position is consumed. |
| Offline reopening | The latest day closed while the app was offline and the next send occurs several dates later. | Resume observes closure and reserves the send. | Closure is persisted once and one new day is created for the current resolved date at the next position; intervening dates have no rows. |
| Spring gap | `America/New_York` advances from UTC-05:00 to UTC-04:00 during `2026-03-08`. | A send resolves that date. | The stored boundaries are `2026-03-08T05:00:00Z` and `2026-03-09T04:00:00Z`; the day lasts 23 hours. |
| Fall fold | `America/New_York` repeats an hour during `2026-11-01`. | A send resolves that date. | The stored boundaries are `2026-11-01T04:00:00Z` and `2026-11-02T05:00:00Z`; the day lasts 25 hours and the fold creates no second day. |
| Persona elsewhere | The Timeline uses the user's Tehran calendar and the persona is authored as living in Florida. | The user opens or sends in Timeline. | Timeline shows no persona-local clock and applies no sleep restriction; all day boundaries remain Tehran boundaries. |
| Host zone changes | A Timeline captured `Asia/Tehran` and the host later reports another zone. | The next operation runs. | The Timeline continues resolving future days in `Asia/Tehran`; no existing or future boundary is rezoned. |
| Concurrent first sends | Two callers observe no day and the same Timeline revision. | Both reserve the first send. | One transaction creates the day and attempt; the other returns a stale/open-attempt result and creates no duplicate date or position. |
| Boundary crossing | A caller reserves at `close - 1 microsecond`, while another action observes the clock at `close`. | Completion and closure race under the same Timeline guard. | Closure wins at or after the stored boundary; the attempt is interrupted and no persona node commits after close. |
