"""List distinct CMCD session and content identifiers."""

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

_TIME_RANGE = re.compile(r"^-\d+[smhdw]$")


class SessionAndContentIds(BaseModel):
    session_ids: list[str]
    content_ids: list[str]
    session_count: int
    content_count: int
    time_range: str


def list_session_and_content_ids(
    time_range: str = "-24h",
    limit: int = 100,
    *,
    query_influxdb: Callable[[str], list[dict[str, Any]]],
) -> SessionAndContentIds:
    """Return distinct session and content ids observed in the time range."""
    if not _TIME_RANGE.fullmatch(time_range) or not 1 <= limit <= 1000:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "Use a valid negative time range and a limit from 1 to 1000.",
            "For example, use time_range=-24h and limit=100.",
        )
    prefix = (
        'from(bucket: "cmcd-metrics")\n'
        f"  |> range(start: {time_range})\n"
        '  |> filter(fn: (r) => r["_measurement"] == "cloudfront_logs")\n'
    )
    sessions = query_influxdb(
        prefix
        + '  |> filter(fn: (r) => exists r["cmcd_sid"])\n'
        + '  |> distinct(column: "cmcd_sid")\n'
        + f"  |> limit(n: {limit})"
    )
    contents = query_influxdb(
        prefix
        + '  |> filter(fn: (r) => exists r["cmcd_cid"])\n'
        + '  |> distinct(column: "cmcd_cid")\n'
        + f"  |> limit(n: {limit})"
    )
    session_ids = _distinct_values(sessions, "cmcd_sid")
    content_ids = _distinct_values(contents, "cmcd_cid")
    return SessionAndContentIds(
        session_ids=session_ids,
        content_ids=content_ids,
        session_count=len(session_ids),
        content_count=len(content_ids),
        time_range=time_range,
    )


def _distinct_values(records: list[dict[str, Any]], key: str) -> list[str]:
    return list(dict.fromkeys(str(record[key]) for record in records if record.get(key)))
