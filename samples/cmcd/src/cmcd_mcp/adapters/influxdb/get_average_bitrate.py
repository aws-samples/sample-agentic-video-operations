"""Calculate average requested bitrate from CMCD records."""

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

from .quote_flux_string import quote_flux_string

_TIME_RANGE = re.compile(r"^-\d+[smhdw]$")


class AverageBitrate(BaseModel):
    average_bitrate_kbps: float
    time_range: str
    session_id: str | None = None
    content_id: str | None = None


def get_average_bitrate(
    time_range: str = "-24h",
    cmcd_sid: str | None = None,
    cmcd_cid: str | None = None,
    *,
    bucket: str,
    query_influxdb: Callable[[str], list[dict[str, Any]]],
) -> AverageBitrate:
    """Return mean CMCD bitrate, optionally filtered by session or content."""
    _require_time_range(time_range)
    filters = [
        'r["_measurement"] == "cloudfront_logs"',
        'r["_field"] == "cmcd_br"',
        'r["_value"] > 0',
    ]
    if cmcd_sid:
        filters.append(f'r["cmcd_sid"] == {quote_flux_string(cmcd_sid)}')
    if cmcd_cid:
        filters.append(f'r["cmcd_cid"] == {quote_flux_string(cmcd_cid)}')
    predicate = " and ".join(filters)
    flux = (
        f"from(bucket: {quote_flux_string(bucket)})\n"
        f"  |> range(start: {time_range})\n"
        f"  |> filter(fn: (r) => {predicate})\n"
        "  |> group()\n"
        "  |> mean()"
    )
    records = query_influxdb(flux)
    value = records[0].get("_value") if records else None
    if not isinstance(value, int | float) or value <= 0:
        raise ToolFailure(
            FailureKind.RESOURCE_NOT_FOUND,
            "No bitrate data matched the requested criteria.",
            "Try a wider time range or list the available session and content ids.",
        )
    return AverageBitrate(
        average_bitrate_kbps=float(value),
        time_range=time_range,
        session_id=cmcd_sid,
        content_id=cmcd_cid,
    )


def _require_time_range(time_range: str) -> None:
    if not _TIME_RANGE.fullmatch(time_range):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The time range must look like -1h, -24h, or -7d.",
            "Use a negative Flux duration with s, m, h, d, or w.",
        )
