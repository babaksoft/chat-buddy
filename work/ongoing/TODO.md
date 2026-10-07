# Ongoing status

Next delivery focus: Stage 6 — Storylines and continuity-scoped memory.

Deferred engineering:

- Calibrate the Ollama token estimate against `prompt_eval_count` for the curated
  cloud models using representative English, Persian, code, long-text, and
  multi-message prompts; adjust the safety margin if the proxy undercounts.
- Replace local imports used for lazy Characters infrastructure composition with
  import-safe session wiring. Prefer a cached session-factory getter that creates
  the SQLAlchemy engine only on explicit use, allowing factory dependencies to
  return to normal module-level imports without initializing persistence when the
  Characters UI is imported. Keep this cleanup behind the current UX hardening
  work and preserve the lazy-initialization architecture tests.
