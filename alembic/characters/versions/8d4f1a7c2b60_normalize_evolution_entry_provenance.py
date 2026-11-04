"""Normalize evolution provenance around Continuity Entries.

Revision ID: 8d4f1a7c2b60
Revises: 4b8e2d7c1a90
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d4f1a7c2b60"
down_revision: str | Sequence[str] | None = "4b8e2d7c1a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add relational Entry ownership and normalize serialized provenance."""

    op.add_column(
        "evolution_effects",
        sa.Column("evidence_kind", sa.String(length=32), nullable=True),
        schema="characters",
    )
    op.add_column(
        "evolution_effects",
        sa.Column("entry_id", sa.Uuid(), nullable=True),
        schema="characters",
    )
    op.execute(
        "UPDATE characters.evolution_effects SET "
        "evidence_kind = CASE source->>'kind' "
        "WHEN 'ongoing_turn' THEN 'ongoing_turn' ELSE 'entry_checkpoint' END, "
        "entry_id = CASE WHEN source->>'kind' = 'storyline_checkpoint' "
        "THEN (source->>'scene_id')::uuid END"
    )
    op.alter_column(
        "evolution_effects", "evidence_kind", nullable=False, schema="characters"
    )
    op.create_foreign_key(
        "fk_evolution_effect_entry",
        "evolution_effects",
        "continuity_entries",
        [
            "entry_id",
            "continuity_id",
            "identity_id",
            "persona_id",
            "conversation_id",
        ],
        ["id", "continuity_id", "identity_id", "persona_id", "conversation_id"],
        source_schema="characters",
        referent_schema="characters",
    )
    op.create_check_constraint(
        "ck_evolution_effect_evidence_shape",
        "evolution_effects",
        "(evidence_kind = 'ongoing_turn' AND entry_id IS NULL) OR "
        "(evidence_kind = 'entry_checkpoint' AND entry_id IS NOT NULL)",
        schema="characters",
    )
    _transform_serialized_provenance("normalize")


def downgrade() -> None:
    """Restore serialized Storyline checkpoint vocabulary and remove Entry links."""

    _transform_serialized_provenance("restore")
    op.drop_constraint(
        "ck_evolution_effect_evidence_shape",
        "evolution_effects",
        schema="characters",
        type_="check",
    )
    op.drop_constraint(
        "fk_evolution_effect_entry",
        "evolution_effects",
        schema="characters",
        type_="foreignkey",
    )
    op.drop_column("evolution_effects", "entry_id", schema="characters")
    op.drop_column("evolution_effects", "evidence_kind", schema="characters")


def _transform_serialized_provenance(direction: str) -> None:
    """Recursively transform every persisted evidence reference.

    Args:
        direction:
            ``normalize`` for Entry vocabulary or ``restore`` for Scene vocabulary.
    """

    if direction == "normalize":
        function_body = """
        IF jsonb_typeof(value) = 'object' THEN
            SELECT COALESCE(
                jsonb_object_agg(key, pg_temp.transform_evolution_reference(item)),
                '{}'::jsonb
            ) INTO result FROM jsonb_each(value) AS fields(key, item);
            IF result->>'kind' = 'storyline_checkpoint' THEN
                result := (result - 'kind' - 'scene_id' - 'scene_position') ||
                    jsonb_build_object(
                        'kind', 'entry_checkpoint',
                        'entry', jsonb_build_object(
                            'entry_id', result->'scene_id',
                            'continuity_id', result#>'{scope,continuity_id}',
                            'mode', 'storyline',
                            'position', result->'scene_position'
                        )
                    );
            END IF;
            RETURN result;
        ELSIF jsonb_typeof(value) = 'array' THEN
            SELECT COALESCE(
                jsonb_agg(pg_temp.transform_evolution_reference(item)),
                '[]'::jsonb
            ) INTO result FROM jsonb_array_elements(value) AS items(item);
            RETURN result;
        END IF;
        RETURN value;
        """
    else:
        function_body = """
        IF jsonb_typeof(value) = 'object' THEN
            SELECT COALESCE(
                jsonb_object_agg(key, pg_temp.transform_evolution_reference(item)),
                '{}'::jsonb
            ) INTO result FROM jsonb_each(value) AS fields(key, item);
            IF result->>'kind' = 'entry_checkpoint' THEN
                result := (result - 'kind' - 'entry') ||
                    jsonb_build_object(
                        'kind', 'storyline_checkpoint',
                        'scene_id', result#>'{entry,entry_id}',
                        'scene_position', result#>'{entry,position}'
                    );
            END IF;
            RETURN result;
        ELSIF jsonb_typeof(value) = 'array' THEN
            SELECT COALESCE(
                jsonb_agg(pg_temp.transform_evolution_reference(item)),
                '[]'::jsonb
            ) INTO result FROM jsonb_array_elements(value) AS items(item);
            RETURN result;
        END IF;
        RETURN value;
        """

    op.execute(
        "CREATE OR REPLACE FUNCTION pg_temp.transform_evolution_reference(value jsonb) "
        "RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$ "
        "DECLARE result jsonb; BEGIN "
        f"{function_body} END; $$"
    )
    for table, columns in (
        ("evolution_effects", ("source", "proposal", "decision")),
        ("evolution_events", ("command",)),
        ("evolution_correction_events", ("replacement",)),
    ):
        for column in columns:
            op.execute(
                f"UPDATE characters.{table} SET {column} = "
                f"pg_temp.transform_evolution_reference({column}::jsonb)::json "
                f"WHERE {column} IS NOT NULL"
            )
