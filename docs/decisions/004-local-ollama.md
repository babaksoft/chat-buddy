# ADR 004: Use a locally installed Ollama service

- Status: Superseded by ADR 014
- Date: 2026-09-09
- Superseded: 2026-09-15

## Context

Chat Buddy is local-first and needs an Ollama endpoint for chat generation and
utility tasks. Ollama now runs as a local installation, while PostgreSQL remains
the only service managed by Docker Compose.

## Decision

Connect to a locally installed Ollama service through its configured HTTP
endpoint. Do not run or manage Ollama in this repository's Docker Compose stack.

## Consequences

- Developers must install, start, and provision the configured models in Ollama.
- Docker Compose remains responsible only for PostgreSQL.
- The endpoint and model names remain application configuration, so local
  deployment details are not embedded in application services.

## Alternatives considered

- Run Ollama in Docker — not selected because it is no longer the chosen local
  operating model and adds container and GPU configuration overhead.
- Use a hosted LLM API — not selected because it conflicts with the local-first
  deployment goal.
