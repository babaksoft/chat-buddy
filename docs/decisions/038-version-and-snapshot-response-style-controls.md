# ADR 038: Version and snapshot user-controlled response presentation

- Status: Accepted
- Date: 2026-11-02
- Last revised: 2026-11-02
- Scope: Characters, Stage 8
- Refines: ADRs 008, 009, 025, and 030
- Consistent with: ADRs 006, 034, 035, and 036

## Context

Characters currently uses fixed internal response instructions. Users need a few
safe, predictable presentation controls, while concurrent saves, retries, and
in-flight generation must not change the meaning or provenance of an existing
response.

Dialogue punctuation and layout are naturally context-dependent. Tone is also not
merely visual presentation: it expresses persona core, adaptation, relationship,
current state, and scene context. Persisting dialogue-format or tone presets would
add artificial structure and could make a persona contradict its authored nature.

## Decision

Store one current response-style setting and optimistic style revision per
continuity in Ongoing, Storyline, and Timeline. Style is continuity-scoped, not
profile-, scene-, day-, conversation-, provider-, or branch-scoped. A writable
active continuity permits a save against the expected revision; archival makes
the setting read-only. A successful save atomically replaces all three requested
controls and increments the revision.

Use only this versioned vocabulary:

| Control | Allowed values | Meaning |
|---|---|---|
| Scene description | `none`, `light`, `balanced`, `rich` | Amount of environmental, action, and non-verbal description. |
| Response length | `concise`, `balanced`, `expansive` | Target response extent, subject to model and context budgets. |
| Narrative placement | `before_dialogue`, `interleaved`, `after_dialogue` | Where any scene description appears relative to ordinary prose or dialogue. |

Unknown values and extra fields are invalid. `none` scene description makes
narrative placement inert but does not make the saved combination invalid. The
renderer still emits every control in stable order so equal settings produce
equal snapshots.

Resolve defaults explicitly by mode:

| Mode | Scene description | Length | Placement |
|---|---|---|---|
| Ongoing | `none` | `balanced` | `interleaved` |
| Storyline | `balanced` | `balanced` | `interleaved` |
| Timeline | `balanced` | `balanced` | `interleaved` |

These defaults initialize a continuity when the user has not selected another
combination. Existing Ongoing and Storyline continuities receive their mode
defaults when persistence is introduced. A Storyline scene no longer owns a fixed
style; its setup remains immutable as defined by ADR 025, while the continuity's
current style applies at each attempt boundary.

Use one fixed, versioned Markdown presentation convention for every Characters
mode; it is renderer behavior, not a user setting:

- Persona scene description and action use simple Markdown italics when scene
  description is enabled.
- Ordinary prose and dialogue remain plain. Bold may be used sparingly for natural
  emphasis.
- Single quotes, double quotes, or both follow language and context rather than a
  configured quotation style.
- A conversation-like exchange narrated inside one message may use any clear
  ordinary Markdown structure, including speaker-labelled lines, lists, or
  blockquotes. No `plain`, `quoted`, or `script` mode is imposed.
- Identity messages may optionally use the same Markdown syntax. The application
  stores the authored text unchanged and does not require or normalize formatting.
- The UI renders identity and persona messages as Markdown with unsafe HTML
  disabled. Raw HTML is not part of the convention.

Markdown is presentation, not structured evidence. Memory extraction, evolution,
summarization, and context eligibility must not treat italics, bold, quotes,
speaker labels, or blockquotes as authoritative scene facts or special provenance.

Do not persist or render a tone control. Persona core defines characteristic tone;
persona adaptation, relationship and current state, scene setup, and current
conversation provide contextual variation. Those sources take precedence without
a competing long-lived `warm`, `playful`, `serious`, `dramatic`, or free-form tone
instruction.

The Characters-owned renderer has a semantic version and produces an immutable
effective `ResponseStyle` containing that renderer identity, all three
resolved values, the source style revision, and the exact deterministic
instruction in the table order above followed by the fixed Markdown convention.
The instruction must fit the existing 4,096-character snapshot limit. Style
instructions govern presentation only. Persona core, adaptation, facts, memory,
relationship state, current scene setup, selected history, and user boundaries
are not style inputs or outputs.

Attempt reservation is the linearization boundary. In the same transaction that
reserves an attempt, read the committed style revision and copy its rendered
snapshot to the attempt. If a style save commits first, the reservation uses the
new revision; if reservation commits first, that attempt keeps the old snapshot.
Completion copies the attempt's exact snapshot to the persona message. A failed
or interrupted attempt retains its snapshot as evidence. No later setting or
renderer change rewrites an attempt, persona message, prompt provenance, summary,
memory, relationship event, or persona-adaptation event.

Incomplete continuation and completed-response retry are new attempts, so each
uses the current committed style when it is reserved. Older failed attempts and
completed persona alternatives retain their original snapshots. Style changes do
not trigger derivation replay because they change presentation, not the selected
facts or evidence.

## Consequences

- Users control response extent and scene-description behavior without configuring
  dialogue punctuation or persona behavior.
- Identity and persona messages share a readable Markdown surface without a
  formatting-mode state machine.
- Every generated response can be explained using the exact presentation
  instruction effective at reservation time.
- Optimistic revisions make concurrent editor saves explicit, while transaction
  ordering makes save-versus-send deterministic.
- Prompt construction consumes a rendered snapshot and does not duplicate style
  formatting rules by mode.
- Future vocabulary or rendering changes require a new renderer version and do
  not alter historical snapshots.

## Alternatives considered

- Offer `plain`, `quoted`, and `script` dialogue formats — rejected because quotes,
  embedded exchanges, and speaker markers are contextual and ordinary Markdown
  already expresses them without persistent mode state.
- Offer bounded or free-form tone controls — rejected because tone participates in
  persona and relationship behavior rather than presentation alone and could
  contradict the persona core.
- Store style on a Storyline scene or Timeline day — rejected because a saved
  change must affect the next attempt without rewriting narrative ownership.
- Resolve style at completion — rejected because a setting changed during provider
  streaming would alter the instruction after generation had already begun.
- Re-render historical values with the latest renderer — rejected because prompt
  provenance would cease to be exact.

## Behavioral examples

| Case | Given | When | Then |
|---|---|---|---|
| Markdown description | Scene description is `balanced`. | The persona describes an action and then speaks. | The action may be italic and the dialogue remains plain; the message is stored as authored Markdown. |
| Embedded exchange | Either participant narrates several speakers inside one message. | They use speaker-labelled bullets or another clear Markdown form. | The UI renders that form without requiring a dialogue-format setting or interpreting it as separate message nodes. |
| Persona tone | A persona core is reserved and matter-of-fact. | A response is generated under any saved style. | No persistent style instruction asks the persona to become playful, warm, dramatic, or otherwise contradict its core. |
| Update before send | Revision 3 is saved successfully before a send transaction starts. | The send reserves attempt A. | A stores the revision-3 rendered snapshot and its completed persona message copies it. |
| Update during attempt | Attempt A reserved revision 3 and is streaming. | Revision 4 is saved. | A keeps revision 3; the next newly reserved attempt uses revision 4. |
| Retry under newer style | Persona alternative P completed with revision 3, then revision 4 is saved. | P is retried. | The retry is a new attempt with revision 4; P and all older alternatives retain revision 3. |
| Concurrent saves | Two editors submit different values against revision 4. | Their transactions race. | One commits revision 5 and the other receives a stale-revision result. |
| Archived continuity | A continuity has been archived. | A style save is requested. | The save is rejected and historical snapshots remain readable. |
