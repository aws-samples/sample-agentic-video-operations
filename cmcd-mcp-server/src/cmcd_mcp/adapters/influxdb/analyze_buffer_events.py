"""Identify low-buffer CMCD events."""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

from .quote_flux_string import quote_flux_string

_TIME_RANGE = re.compile(r"^-\d+[smhdw]$")


class BufferEvent(BaseModel):
    at: datetime
    buffer_level_ms: float
    session_id: str
    edge_location: str | None = None
    cdn: str | None = None


class BufferAnalysis(BaseModel):
    total_events: int
    low_buffer_count: int
    low_buffer_events: list[BufferEvent]
    threshold_ms: int


def analyze_buffer_events(
    time_range: str = "-24h",
    cmcd_sid: str | None = None,
    threshold_ms: int = 500,
    *,
    query_influxdb: Callable[[str], list[dict[str, Any]]],
) -> BufferAnalysis:
    """Return buffer events below the requested threshold."""
    if not _TIME_RANGE.fullmatch(time_range) or threshold_ms < 0:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "Use a valid negative time range and a non-negative threshold.",
            "For example, use time_range=-24h and threshold_ms=500.",
        )
    sid_filter = f' and r["cmcd_sid"] == {quote_flux_string(cmcd_sid)}' if cmcd_sid else ""
    flux = (
        'from(bucket: "cmcd-metrics")\n'
        f"  |> range(start: {time_range})\n"
        '  |> filter(fn: (r) => r["_measurement"] == "cloudfront_logs" '
        f'and r["_field"] == "cmcd_bl"{sid_filter})\n'
        '  |> sort(columns: ["_time"])'
    )
    records = query_influxdb(flux)
    events = [_to_event(record) for record in records if _is_numeric(record.get("_value"))]
    if not events:
        raise ToolFailure(
            FailureKind.RESOURCE_NOT_FOUND,
            "No buffer-level data matched the requested criteria.",
            "Try a wider time range or another session id.",
        )
    low_events = [event for event in events if event.buffer_level_ms < threshold_ms]
    return BufferAnalysis(
        total_events=len(events),
        low_buffer_count=len(low_events),
        low_buffer_events=low_events,
        threshold_ms=threshold_ms,
    )


def _is_numeric(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _to_event(record: dict[str, Any]) -> BufferEvent:
    return BufferEvent(
        at=record["_time"],
        buffer_level_ms=float(record["_value"]),
        session_id=str(record.get("cmcd_sid", "unknown")),
        edge_location=record.get("edge_location"),
        cdn=record.get("cdn"),
    )
