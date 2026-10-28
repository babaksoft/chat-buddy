"""Shared validation patterns for Characters domain values."""

MACHINE_READABLE_NAME_PATTERN = r"^[a-z][a-z0-9_.-]*$"
NON_BLANK_TEXT_PATTERN = r"\S"
SEMANTIC_VERSION_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
