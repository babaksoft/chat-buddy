# ADR 003: Store persistent data in PostgreSQL

- Status: Accepted
- Date: 2026-09-09

## Context

Chat Buddy persists conversations and will add continuity-scoped memories,
relationship state, and branching data. The project needs a durable relational
database suitable for realistic production-style migrations and testing.

## Decision

Use PostgreSQL as the persistent application database, accessed through
SQLAlchemy and evolved with Alembic migrations.

## Consequences

- Local development requires a PostgreSQL service; Docker Compose provides it.
- The project gains transactional and relational capabilities for future domain
  invariants.
- Database setup is more involved than file-backed or embedded storage.

## Alternatives considered

- SQLite — not selected because PostgreSQL better reflects the intended
  production database environment.
- JSON files — not selected because they do not provide the required relational
  integrity or migration workflow.
