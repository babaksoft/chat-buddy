EXTRACT_MEMORY_PROMPT = """Extract long-term facts about the user.

Return ONLY valid JSON.

The JSON must be an array of objects.

Each object must have exactly these fields:

- key
- value

Example:

[
  {
    "key": "favorite_language",
    "value": "Python"
  },
  {
    "key": "preferred_editor",
    "value": "VS Code"
  }
]

Rules:

- Extract only durable facts that the user states or clearly confirms.
- Use the assistant response only as conversational evidence; never store an
  unsupported assistant assertion as a fact about the user.
- Ignore temporary information.
- Do not explain your answer.
- Do not wrap the JSON in markdown.
- Return [] if no memories should be stored."""

MEMORY_CONTEXT_HEADER = "Known facts about the user:"
