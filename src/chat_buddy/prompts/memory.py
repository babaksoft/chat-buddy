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

- Ignore temporary information.
- Ignore assistant messages.
- Do not explain your answer.
- Do not wrap the JSON in markdown.
- Return [] if no memories should be stored."""
