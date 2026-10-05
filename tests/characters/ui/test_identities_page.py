"""Service-double acceptance tests for focused identity management."""

from collections.abc import Generator
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from chat_buddy.characters.application import IdentityService
from chat_buddy.characters.domain import (
    FrozenIdentityError,
    Identity,
    IdentityDetails,
    StaleIdentityError,
)
from chat_buddy.characters.ui import identities_page


def _render() -> None:
    """Render only the focused Identities page."""

    from chat_buddy.characters.ui import render_identities

    render_identities()


@pytest.fixture
def identity_service() -> Generator[Mock, None, None]:
    """Provide identity application operations and persisted snapshots.

    Yields:
        Configured identity service double.
    """

    default = Identity(
        id=uuid4(),
        details=IdentityDetails(
            name="You",
            gender="nonbinary",
            age=36,
            pronouns="they/them",
            preferred_address="Alex",
            timezone="Asia/Tehran",
        ),
        is_default=True,
    )
    other = Identity(id=uuid4(), details=IdentityDetails(name="Traveler"))
    service = Mock(spec=IdentityService)
    service.ensure_default.return_value = default
    service.list.return_value = [default, other]
    with patch.object(identities_page, "create_identity_service", return_value=service):
        yield service


def test_lists_names_summaries_and_complete_selected_details(
    identity_service: Mock,
) -> None:
    """Show persisted identity attributes and edit state without derived data.

    Args:
        identity_service:
            Identity service double.
    """

    app = AppTest.from_function(_render).run()

    assert not app.exception
    assert app.title[0].value == "🪪 Identities"
    assert any(
        "Alex · they/them · nonbinary · Age 36 · Asia/Tehran" in item.value
        for item in app.caption
    )
    assert any("No additional details" in item.value for item in app.caption)
    assert (
        next(field for field in app.text_input if field.label == "Identity name").value
        == "You"
    )
    identity_service.ensure_default.assert_called_once_with()


def test_creates_and_immediately_selects_new_identity(
    identity_service: Mock,
) -> None:
    """Create an identity and show the persisted result in the existing list.

    Args:
        identity_service:
            Identity service double.
    """

    created = Identity(id=uuid4(), details=IdentityDetails(name="New identity"))

    def create(details: IdentityDetails) -> Identity:
        """Expose the simulated persisted result to the following rerun.

        Args:
            details:
                Submitted authored identity details.

        Returns:
            Newly persisted identity snapshot.
        """

        nonlocal created
        created = created.model_copy(update={"details": details})
        identity_service.list.return_value.append(created)
        return created

    identity_service.create.side_effect = create
    app = AppTest.from_function(_render).run()
    app.button(key="characters_identity_new_action").click().run()
    next(field for field in app.text_input if field.label == "Identity name").set_value(
        "New identity"
    )
    next(
        button for button in app.button if button.label == "Create identity"
    ).click().run()

    assert not app.exception
    identity_service.create.assert_called_once_with(
        IdentityDetails(name="New identity")
    )
    assert app.session_state["characters_identity_id"] == created.id
    assert app.button(key=f"characters_identity_manage_{created.id}")
    assert (
        next(field for field in app.text_input if field.label == "Identity name").value
        == "New identity"
    )


def test_saves_editable_identity_with_expected_revision(
    identity_service: Mock,
) -> None:
    """Replace an unused identity and retain its stable selection.

    Args:
        identity_service:
            Identity service double.
    """

    original = cast(Identity, identity_service.list.return_value[0])

    def edit(
        identity_id: object, details: IdentityDetails, expected_revision: int
    ) -> Identity:
        """Replace the service double's current snapshot.

        Args:
            identity_id:
                Stable identity identifier.
            details:
                Submitted replacement fields.
            expected_revision:
                Revision displayed in the form.

        Returns:
            Revised persisted identity snapshot.
        """

        revised = original.model_copy(
            update={"details": details, "revision": expected_revision + 1}
        )
        identity_service.list.return_value[0] = revised
        return revised

    identity_service.edit.side_effect = edit
    app = AppTest.from_function(_render).run()
    next(field for field in app.text_input if field.label == "Identity name").set_value(
        "Revised"
    )
    next(
        button for button in app.button if button.label == "Save changes"
    ).click().run()

    assert not app.exception
    replacement = identity_service.edit.call_args.args[1]
    assert replacement.name == "Revised"
    identity_service.edit.assert_called_once_with(
        original.id, replacement, original.revision
    )
    assert app.session_state["characters_identity_id"] == original.id


def test_frozen_identity_explains_and_duplicates_edited_values(
    identity_service: Mock,
) -> None:
    """Keep history immutable while allowing a customized independent copy.

    Args:
        identity_service:
            Identity service double.
    """

    source = cast(Identity, identity_service.list.return_value[0]).model_copy(
        update={"is_frozen": True}
    )
    identity_service.list.return_value[0] = source
    duplicate = source.model_copy(
        update={"id": uuid4(), "is_default": False, "is_frozen": False}
    )

    def copy(identity_id: object, details: IdentityDetails) -> Identity:
        """Expose the customized duplicate to the following rerun.

        Args:
            identity_id:
                Source identity identifier.
            details:
                Revised copied fields.

        Returns:
            Independent editable identity snapshot.
        """

        revised = duplicate.model_copy(update={"details": details})
        identity_service.list.return_value.append(revised)
        return revised

    identity_service.duplicate.side_effect = copy
    app = AppTest.from_function(_render).run()
    assert "rewrite that history" in app.info[0].value
    next(field for field in app.text_input if field.label == "Identity name").set_value(
        "Alternate"
    )
    next(
        button for button in app.button if button.label == "Duplicate identity"
    ).click().run()

    assert not app.exception
    revised_details = identity_service.duplicate.call_args.args[1]
    assert revised_details.name == "Alternate"
    identity_service.duplicate.assert_called_once_with(source.id, revised_details)
    identity_service.edit.assert_not_called()
    assert app.session_state["characters_identity_id"] == duplicate.id


@pytest.mark.parametrize(
    "error",
    [
        FrozenIdentityError("Duplicate this frozen identity to edit it"),
        StaleIdentityError("Reload the identity before editing"),
    ],
)
def test_concurrent_edit_conflict_is_visible(
    identity_service: Mock, error: ValueError
) -> None:
    """Surface a freeze or stale revision racing with an editable submission.

    Args:
        identity_service:
            Identity service double.
        error:
            Concurrent service failure to present.
    """

    identity_service.edit.side_effect = error
    app = AppTest.from_function(_render).run()
    next(
        button for button in app.button if button.label == "Save changes"
    ).click().run()

    assert not app.exception
    assert str(error) in app.error[0].value
