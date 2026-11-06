"""Characters-owned production time and local-timezone implementations."""

import os
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import available_timezones


class SystemUtcClock:
    """Read the current system instant as aware UTC for production composition."""

    def now(self) -> datetime:
        """Return the current aware UTC instant.

        Returns:
            Current system instant expressed in UTC.
        """

        return datetime.now(UTC)


class SystemLocalTimezoneSource:
    """Resolve the application runtime's local IANA timezone."""

    def timezone_name(self) -> str:
        """Return the best available installed IANA timezone identifier.

        Returns:
            Runtime-local IANA timezone, falling back to UTC when the host exposes
            only a fixed offset.
        """

        candidates = (
            os.environ.get("TZ"),
            self._datetime_zone(),
            self._etc_timezone(),
            self._localtime_zone(),
        )
        installed = available_timezones()
        return next(
            (candidate for candidate in candidates if candidate in installed), "UTC"
        )

    @staticmethod
    def _datetime_zone() -> str | None:
        """Read a named zone exposed by the standard-library local clock.

        Returns:
            IANA-like zone key or None.
        """

        return getattr(datetime.now().astimezone().tzinfo, "key", None)

    @staticmethod
    def _etc_timezone() -> str | None:
        """Read the conventional host timezone declaration when available.

        Returns:
            Declared zone name or None.
        """

        try:
            return Path("/etc/timezone").read_text(encoding="utf-8").strip()
        except OSError:
            return None

    @staticmethod
    def _localtime_zone() -> str | None:
        """Derive a zone name from the conventional localtime symlink.

        Returns:
            Zoneinfo-relative path or None.
        """

        try:
            resolved = Path("/etc/localtime").resolve(strict=True)
        except OSError:
            return None
        marker = "zoneinfo/"
        path = str(resolved)
        return path.split(marker, 1)[1] if marker in path else None
