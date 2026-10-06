"""Read the current UTC time at runtime boundaries."""

from datetime import UTC, datetime


def read_utc_now() -> datetime:
    """Return the wall clock in UTC."""
    return datetime.now(UTC)
