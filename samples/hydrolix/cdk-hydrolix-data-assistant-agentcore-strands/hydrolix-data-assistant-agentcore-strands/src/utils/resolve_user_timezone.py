"""The caller's timezone goes into the system prompts, so only a real IANA zone name may."""

from functools import lru_cache
from zoneinfo import available_timezones

DEFAULT_TIMEZONE = "US/Pacific"
FALLBACK_TIMEZONE = "UTC"


@lru_cache(maxsize=1)
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def resolve_user_timezone(value: object = DEFAULT_TIMEZONE) -> str:
    """`value` if it names a known zone; UTC for anything else, text included."""
    if isinstance(value, str) and value in _known_timezones():
        return value
    return FALLBACK_TIMEZONE
