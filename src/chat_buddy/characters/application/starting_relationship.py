"""Mode-neutral starting relationship resolution."""

from chat_buddy.characters.domain import (
    RelationshipSelection,
    StartingOrigins,
    StartingRelationship,
)


def resolve_starting_relationship(
    selection: RelationshipSelection,
) -> StartingRelationship:
    """Resolve omitted reviewed fields to their documented defaults.

    Args:
        selection:
            Reviewed relationship inputs with omission provenance.

    Returns:
        Complete immutable starting state and field origins.
    """

    defaults: dict[str, object] = {
        "social": "stranger",
        "romantic": "none",
        "dynamic": "neutral",
        "trust": "unknown",
        "affection": "neutral",
        "boundaries": (),
    }
    origins = {}
    for field, default in defaults.items():
        value = getattr(selection, field)
        defaults[field] = default if value is None else value
        origins[field] = "default" if value is None else "user_selected"

    return StartingRelationship.model_validate(
        {
            "intent": selection.intent,
            **defaults,
            "origins": StartingOrigins.model_validate(origins),
        }
    )
