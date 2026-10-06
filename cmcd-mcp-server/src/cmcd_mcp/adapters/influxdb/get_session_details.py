"""Group CMCD telemetry for one playback session."""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

from .quote_flux_string import quote_flux_string

_TIME_RANGE = re.compile(r"^-\d+[smhdw]$")


class MetricPoint(BaseModel):
    at: datetime
    value: float | int | str | bool | None


class SessionDetails(BaseModel):
    session_id: str
    start_time: datetime
    end_time: datetime
    metrics: dict[str, list[MetricPoint]]


def get_session_details(
    cmcd_sid: str,
    time_range: str = "-24h",
    *,
    query_influxdb: Callable[[str], list[dict[str, Any]]],
) -> SessionDetails:
    """Return chronologically grouped metrics for one CMCD session."""
    if not _TIME_RANGE.fullmatch(time_range):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The time range must look like -1h, -24h, or -7d.",
            "Use a negative Flux duration with s, m, h, d, or w.",
        )
    flux = (
        'from(bucket: "cmcd-metrics")\n'
        f"  |> range(start: {time_range})\n"
        '  |> filter(fn: (r) => r["_measurement"] == "cloudfront_logs")\n'
        f'  |> filter(fn: (r) => r["cmcd_sid"] == {quote_flux_string(cmcd_sid)})\n'
        '  |> sort(columns: ["_time"])'
    )
    records = query_influxdb(flux)
    if not records:
        raise ToolFailure(
            FailureKind.RESOURCE_NOT_FOUND,
            f"No CMCD data was found for session {cmcd_sid}.",
            "List the available session ids and retry.",
        )

    metrics: dict[str, list[MetricPoint]] = {}
    for record in records:
        field = record.get("_field")
        timestamp = record.get("_time")
        if isinstance(field, str) and timestamp is not None:
            metrics.setdefault(field, []).append(
                MetricPoint(at=timestamp, value=record.get("_value"))
            )
    return SessionDetails(
        session_id=cmcd_sid,
        start_time=records[0]["_time"],
        end_time=records[-1]["_time"],
        metrics=metrics,
    )
