"""Require a bounded history window before any MediaLive metric or log read."""

from typing import Annotated

from annotated_types import Ge, Le

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

MIN_HOURS_BACK = 1
MAX_HOURS_BACK = 168
HoursBack = Annotated[int, Ge(MIN_HOURS_BACK), Le(MAX_HOURS_BACK)]


def require_hours_back(hours_back: int) -> int:
    if not MIN_HOURS_BACK <= hours_back <= MAX_HOURS_BACK:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"hours_back must be between {MIN_HOURS_BACK} and {MAX_HOURS_BACK}.",
            "Use a window from one hour to seven days.",
        )
    return hours_back
