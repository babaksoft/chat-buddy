# ADR 024: Confirm Ongoing starts and archive explicitly

- Status: Accepted
- Date: 2026-10-01
- Scope: Characters, Stage 4

## Decision

A confirmed Ongoing start creates its continuity, sole conversation, and starting
relationship together with first-use profile freezing. It uses the reviewed
identity and persona revisions; an intervening edit requires renewed review.

An identical confirmation resubmission returns its original continuity, including
after archival. Reusing a confirmation identifier for changed inputs is rejected.
Each identity/persona pair has at most one active Ongoing. Archive is explicit,
permanent, and read-only. A replacement requires a new confirmation and fresh
starting relationship; profiles remain frozen.

Starting fields retain user-selected or default provenance. Established starts
require explicit social and established romantic statuses and invent no shared
events. Relationship restrictions must agree with the selected intent and status.

## Rationale

Atomic creation preserves confirmed profile semantics. Persisted confirmations
prevent duplicate starts across sessions. Explicit archival and independent
starting snapshots preserve each continuity's history and meaning.
