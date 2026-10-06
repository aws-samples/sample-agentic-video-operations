"""Detect likely playback-impacting patterns in CMCD telemetry."""

import re
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

from .quote_flux_string import quote_flux_string

_TIME_RANGE = re.compile(r"^-\d+[smhdw]$")


class PlaybackIssueKind(StrEnum):
    BUFFER_STARVATION = "buffer_starvation"
    SUDDEN_BUFFER_DROP = "sudden_buffer_drop"


class PlaybackIssue(BaseModel):
    kind: PlaybackIssueKind
    severity: str
    at: datetime
    session_id: str
    observed_ms: float | None = None
    observed_flag: bool | None = None
    previous_ms: float | None = None


class PlaybackErrorAnalysis(BaseModel):
    total_issues: int
    issues: list[PlaybackIssue]
    time_range: str
    session_id: str | None = None
    startup_observed: bool


def identify_playback_errors(
    time_range: str = "-24h",
    cmcd_sid: str | None = None,
    *,
    bucket: str,
    query_influxdb: Callable[[str], list[dict[str, Any]]],
) -> PlaybackErrorAnalysis:
    """Return starvation signals and sudden buffer drops with startup context."""
    if not _TIME_RANGE.fullmatch(time_range):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The time range must look like -1h, -24h, or -7d.",
            "Use a negative Flux duration with s, m, h, d, or w.",
        )
    sid_filter = f' and r["cmcd_sid"] == {quote_flux_string(cmcd_sid)}' if cmcd_sid else ""
    base = (
        f"from(bucket: {quote_flux_string(bucket)})\n"
        f"  |> range(start: {time_range})\n"
        '  |> filter(fn: (r) => r["_measurement"] == "cloudfront_logs" '
    )
    buffer_records = query_influxdb(
        base + f'and r["_field"] == "cmcd_bl"{sid_filter})\n  |> sort(columns: ["_time"])'
    )
    starvation_records = query_influxdb(
        base + f'and r["_field"] == "cmcd_bs"{sid_filter})\n  |> sort(columns: ["_time"])'
    )
    startup_records = query_influxdb(
        base + f'and r["_field"] == "cmcd_su"{sid_filter})\n  |> sort(columns: ["_time"])'
    )
    issues = _find_buffer_drops(buffer_records) + _find_starvation_issues(starvation_records)
    return PlaybackErrorAnalysis(
        total_issues=len(issues),
        issues=issues,
        time_range=time_range,
        session_id=cmcd_sid,
        startup_observed=any(record.get("_value") is True for record in startup_records),
    )


def _find_buffer_drops(records: list[dict[str, Any]]) -> list[PlaybackIssue]:
    issues: list[PlaybackIssue] = []
    previous: float | None = None
    for record in records:
        value = record.get("_value")
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        current = float(value)
        if previous is not None and previous > 1000 and current < previous * 0.5:
            issues.append(
                _issue(
                    PlaybackIssueKind.SUDDEN_BUFFER_DROP,
                    "medium",
                    record,
                    current,
                    previous,
                )
            )
        previous = current
    return issues


def _find_starvation_issues(records: list[dict[str, Any]]) -> list[PlaybackIssue]:
    issues: list[PlaybackIssue] = []
    for record in records:
        if record.get("_value") is True:
            issues.append(
                _issue(
                    PlaybackIssueKind.BUFFER_STARVATION,
                    "high",
                    record,
                    observed_flag=True,
                )
            )
    return issues


def _issue(
    kind: PlaybackIssueKind,
    severity: str,
    record: dict[str, Any],
    observed_ms: float | None = None,
    previous: float | None = None,
    observed_flag: bool | None = None,
) -> PlaybackIssue:
    return PlaybackIssue(
        kind=kind,
        severity=severity,
        at=record["_time"],
        session_id=str(record.get("cmcd_sid", "unknown")),
        observed_ms=observed_ms,
        observed_flag=observed_flag,
        previous_ms=previous,
    )
