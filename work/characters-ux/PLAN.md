# Characters UX Hardening Plan

Status: In progress

Last updated: 2026-10-05

## Purpose

Replace the combined Characters prototype screen with focused profile,
continuity-navigation, start-review, and Ongoing chat experiences before adding
retry and branching. Preserve the existing Characters domain rules and keep all
persistence behind application services.

## UX decisions

- Provide dedicated **Ongoing**, **Identities**, **Personas**, and **New Ongoing**
  pages.
- Build the continuity hierarchy from native Streamlit expanders and controls;
  do not add a tree-widget dependency.
- Treat the last Ongoing as the last continuity selected in the current session.
  Durable recency is outside this work because continuities do not persist
  creation or last-viewed timestamps.
- Keep frozen profile fields editable in the UI, but replace saving with
  duplication so the revised authored values create a new profile.
- Derive compact profile summaries from persisted authored fields without an LLM
  call or a new stored value.

## Slice 1 — Dedicated Identities page

**Status: Complete.**

- Add a separately routed Identities page with a master-detail layout.
- List every identity by name, edit state, and a concise summary of its persisted
  authored attributes.
- Allow complete revision-checked edits before first use.
- Explain permanent first-use freezing in short user-facing language.
- Allow frozen identities to be revised into independent duplicates.
- Select and display a newly created or duplicated identity immediately.
- Preserve the selected identity when returning to the Characters page.

**Complete when:** creation, selection, summaries, editable saves, customized
frozen duplication, stale edits, and concurrent freezes have focused Streamlit
coverage and the relevant quality checks pass.

## Slice 2 — Dedicated Personas page

**Status: Complete.**

- Add a separately routed Personas master-detail page.
- List persona names, concise definition excerpts, and edit state.
- Show only one creation or editing form at a time.
- Save unused persona cores and duplicate frozen cores with revised form values.
- Select newly created and duplicated personas immediately.

**Complete when:** all existing persona management operations are available in a
focused page with service-double and integration coverage.

## Slice 3 — Ongoing page and continuity hierarchy

- Extract Ongoing history and chat from the combined Characters page.
- Render all identities, their available personas, and existing active and
  archived continuities as a nested sidebar hierarchy.
- Store and validate the complete identity, persona, and continuity scope when a
  continuity is selected.
- Add an application-level start-availability result so invalid pair controls can
  be disabled with a concise reason without duplicating lifecycle rules in UI.
- Keep archived continuities selectable and read-only.

**Complete when:** every continuity is reachable through its ownership hierarchy,
cross-owner selections cannot resume, and each identity/persona pair exposes a
clear valid or disabled new-Ongoing action.

## Slice 4 — Dedicated New Ongoing workflow

- Move start definition and review to one dedicated page with explicit
  **Define Ongoing** and **Preview Ongoing** states.
- Preserve a draft across ordinary reruns and discard its review if either profile
  revision changes.
- Confirm through the existing atomic start operation, select the returned
  continuity, and navigate to its chat.
- Cancel without writes or freezing and return to the last selected Ongoing, or
  the empty Ongoing page when none was selected.
- Recheck start availability on render and retain the service's race-safe guard
  during confirmation.

**Complete when:** define, preview, stale review, cancellation, confirmation,
duplicate submission, and concurrent active-pair behavior are covered through the
UI and real Characters services.

## Slice 5 — Integration cleanup and documentation

- Remove the legacy inline profile and start controls after replacement pages are
  covered.
- Add end-to-end page and area switching scenarios, including action replay
  prevention and selected-scope restoration.
- Update the stable README for the shipped Characters workflow.
- Run the complete repository checks and confirm Characters still initializes
  independently of Chat.

**Complete when:** the prototype composition is gone, the focused workflow is
documented, and the full CI-equivalent suite passes.

## Boundaries

- Do not add Storyline, Timeline, retry, branching, memory, or relationship
  evolution behavior.
- Do not add profile or continuity persistence solely for presentation state.
- Do not query repositories or SQLAlchemy from UI code.
- Do not change profile freezing, continuity ownership, or atomic confirmation
  semantics accepted by ADRs 007, 023, and 024.
