"""Privacy boundaries for structured Characters diagnostics."""

import logging
from uuid import uuid4

import pytest
from pydantic import ValidationError

from chat_buddy.characters.domain import (
    CharactersDiagnostic,
    CharactersDiagnosticName,
    ContinuityMode,
)
from chat_buddy.characters.infrastructure import LoggingCharactersDiagnosticObserver


def test_logger_emits_only_validated_allowlisted_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep conversation text, prompts, and style instructions out of log records.

    Args:
        caplog:
            Captured structured log records.
    """

    continuity_id = uuid4()
    observer = LoggingCharactersDiagnosticObserver()
    caplog.set_level(logging.INFO)

    observer.emit(
        CharactersDiagnostic(
            name=CharactersDiagnosticName.RESPONSE_CONTEXT_ASSEMBLY,
            continuity_id=continuity_id,
            mode=ContinuityMode.TIMELINE,
            policy="baseline.timeline_response_context",
            version="1.0.0",
            terminal_reason="assembled",
            included_turn_count=2,
            omitted_turn_count=1,
            token_count=512,
        )
    )

    record = caplog.records[-1]
    assert record.__dict__["characters_name"] == "response_context_assembly"
    assert record.__dict__["characters_continuity_id"] == str(continuity_id)
    assert record.__dict__["characters_terminal_reason"] == "assembled"
    assert not any(
        key in record.__dict__
        for key in ("conversation_text", "persona_details", "prompt", "instruction")
    )


def test_diagnostic_contract_rejects_unallowlisted_sensitive_fields() -> None:
    """Reject accidental prompt content before it reaches logging infrastructure."""

    with pytest.raises(ValidationError):
        CharactersDiagnostic.model_validate(
            {
                "name": "attempt_recovery",
                "terminal_reason": "recovered",
                "raw_prompt": "sensitive",
            }
        )
