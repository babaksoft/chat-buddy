# ADR 023: Manage Characters identities with safe edits and default setup

- Status: Accepted
- Date: 2026-10-01
- Scope: Characters, Stage 4 Slice 1

## Context

Identity edits before first use must not silently overwrite competing changes.
Characters needs a default identity independent of Chat setup.

## Decision

Edits retain identity ownership and leave previously observed snapshots unchanged.
Stale edits are rejected and require reloading. All authored fields freeze at
first continuity use as specified in ADR 007.

Create the sole Characters default identity on Characters demand, initially named
**You**, with unknown demographics. Repeated or concurrent setup returns the same
identity; changing its display name retains its default designation.

Duplicates copy only authored details, optionally revised, and start editable,
non-default, and without continuity history. Demographics are optional; age and
birth date are alternative inputs, and timezone is optional for Ongoing.

## Consequences

- Competing edits cannot silently discard another author's changes.
- Characters setup works independently across application sessions.
- Identity setup requires no fabricated personal information.

## Alternatives considered

- Last-write-wins edits: silently lose competing changes.
- Session-local default setup: can create multiple default identities.
