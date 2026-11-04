# Ongoing status

Next delivery focus: Stage 8 Continuity Entry structural refactor, Slice 7 — 
Remove transitional concepts and prove isolation. Cleanup is implemented; completion
is blocked by invalid PostgreSQL backfill SQL in applied revision `9c4e7a1b2d30`.
See the [refactor verification status](CONTINUITY_ENTRY_REFACTOR_PLAN.md#slice-7--remove-transitional-concepts-and-prove-isolation).
This refactor is a prerequisite for
Stage 8, Slice 10.

Deferred product exploration:

- Evaluate a future **Continue this moment in a new Storyline** action for closed
  Timeline messages. Treat it as an explicit mode transition rather than a
  Timeline branch, preserve the closed Timeline unchanged, and decide whether to
  pursue it only after observing closed-message action attempts, mode switching,
  abandonment, and related user feedback. Define privacy-conscious telemetry and
  the exact context-transfer contract before scheduling implementation.

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
