# ADR 005: Separate persistence behind repository protocols

- Status: Accepted
- Date: 2026-09-09

## Context

Application services need persistence without depending on SQLAlchemy queries or
database models. The domain layer defines the contracts that infrastructure
repositories implement.

## Decision

Use a repository layer between application services and SQLAlchemy. Declare
repository `Protocol` interfaces in the domain layer and implement them in
infrastructure.

## Consequences

- Business rules can be tested against repository doubles and remain independent
  of persistence technology.
- UI and application services do not issue direct SQLAlchemy queries.
- The additional abstraction requires repository contracts and implementations
  to evolve together.

## Alternatives considered

- Direct SQLAlchemy usage in services — not selected because it couples business
  rules to persistence and makes focused service tests harder.
