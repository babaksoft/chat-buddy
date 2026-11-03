"""Characters-owned production clock implementation."""

from datetime import UTC, datetime


class SystemUtcClock:
    """Read the current system instant as aware UTC for production composition."""

    def now(self) -> datetime:
        """Return the current aware UTC instant.

        Returns:
            Current system instant expressed in UTC.
        """

        return datetime.now(UTC)
