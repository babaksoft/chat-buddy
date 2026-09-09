# ADR 002: Use Streamlit for the MVP user interface

- Status: Accepted
- Date: 2026-09-09

## Context

Chat Buddy needs a local, interactive interface for chat, conversation history,
and future continuity-management workflows while the product is being developed.

## Decision

Use Streamlit for the MVP user interface. Keep the UI thin and compose
application services in `ui/streamlit_app.py`.

## Consequences

- Chat-oriented components and rapid iteration are available without building a
  separate frontend application.
- Presentation customization is more constrained than with a bespoke web
  frontend.
- Business rules remain in application and domain layers rather than Streamlit
  callbacks.

## Alternatives considered

- FastAPI with React — not selected because it adds a separate frontend and API
  delivery surface for the MVP.
- Gradio — not selected because Streamlit is the selected application framework.
