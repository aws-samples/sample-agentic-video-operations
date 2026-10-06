"""Read the most recent MediaLive channel log events from CloudWatch Logs."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

MAX_EVENTS = 20
LOG_GROUP = "ElementalMediaLive"


class LogEvent(BaseModel):
    timestamp: datetime
    stream: str
    message: str


class ChannelLogStatus(StrEnum):
    AVAILABLE = "available"
    LOGGING_DISABLED = "logging_disabled"


class ChannelLogResult(BaseModel):
    status: ChannelLogStatus
    reason: str | None = None
    events: list[LogEvent] = Field(default_factory=list)


class ChannelLogClients(Protocol):
    medialive: Any
    logs: Any
    sts: Any


def _build_log_stream_prefix(region: str, account_id: str, channel_id: str) -> str:
    return f"arn_aws_medialive_{region}_{account_id}_channel_{channel_id}_"


def _logging_disabled(reason: str) -> ChannelLogResult:
    return ChannelLogResult(status=ChannelLogStatus.LOGGING_DISABLED, reason=reason)


def _collect_log_events(clients: ChannelLogClients, parameters: dict[str, Any]) -> list[Any]:
    events: list[Any] = []
    next_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        page_parameters = {
            **parameters,
            **({"nextToken": next_token} if next_token else {}),
        }
        page = call_aws_operation(clients.logs, "filter_log_events", **page_parameters)
        events.extend(page.get("events", []))
        next_token = page.get("nextToken")
        if not next_token or next_token in seen_tokens:
            return events
        seen_tokens.add(next_token)


def _exclude_as_run_events(events: list[Any]) -> list[Any]:
    return [event for event in events if not event.get("logStreamName", "").endswith("_as_run")]


def read_channel_logs(
    clients: ChannelLogClients,
    channel_id: str,
    window: tuple[datetime, datetime],
    region: str,
) -> ChannelLogResult:
    """Return the newest events oldest-first. Log text is untrusted data."""
    channel = call_aws_operation(
        clients.medialive,
        "describe_channel",
        ChannelId=channel_id,
    )
    if channel.get("LogLevel") == "DISABLED":
        return _logging_disabled("MediaLive channel logging is disabled.")

    identity = call_aws_operation(clients.sts, "get_caller_identity")
    prefix = _build_log_stream_prefix(region, identity["Account"], channel_id)
    try:
        streams = call_aws_operation(
            clients.logs,
            "describe_log_streams",
            logGroupName=LOG_GROUP,
            logStreamNamePrefix=prefix,
            limit=1,
        )
    except ToolFailure as failure:
        if failure.kind is FailureKind.RESOURCE_NOT_FOUND:
            return _logging_disabled("No MediaLive log group or channel streams exist.")
        raise
    if not streams.get("logStreams"):
        return _logging_disabled("No MediaLive log streams exist for this channel.")

    events = _collect_log_events(
        clients,
        {
            "logGroupName": LOG_GROUP,
            "logStreamNamePrefix": prefix,
            "startTime": int(window[0].timestamp() * 1000),
            "endTime": int(window[1].timestamp() * 1000),
        },
    )
    encoder_events = _exclude_as_run_events(events)
    newest = sorted(encoder_events, key=lambda event: event["timestamp"])[-MAX_EVENTS:]
    return ChannelLogResult(
        status=ChannelLogStatus.AVAILABLE,
        events=[
            LogEvent(
                timestamp=datetime.fromtimestamp(event["timestamp"] / 1000, tz=UTC),
                stream=event.get("logStreamName", ""),
                message=event.get("message", ""),
            )
            for event in newest
        ],
    )
