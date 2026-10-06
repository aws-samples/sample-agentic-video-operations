"""Read-only health checks over channel metrics: summaries, issue reports and chart rows."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.cloudwatch.read_channel_metrics import read_channel_metrics
from medialive_mcp.adapters.media_live.describe_channel import describe_channel
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.domain.identify_channel_issues import (
    ChannelContext,
    ChannelHealthReport,
    identify_channel_issues,
)
from medialive_mcp.domain.metric_catalog import (
    ALL_METRICS,
    CATEGORY_METRICS,
    SUMMARY_METRICS,
    TABLE_METRICS,
)
from medialive_mcp.domain.metric_series import MetricSeries


class MetricRow(BaseModel):
    timestamp: datetime
    category: str
    metric: str
    pipeline: str
    value: float


def recent_window(hours_back: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    end = now or datetime.now(UTC)
    return end - timedelta(hours=hours_back), end


def summarize_channel_metrics(
    clients: MediaLiveClients, channel_id: str, hours_back: int, category: str | None = None
) -> list[MetricSeries]:
    if category and category not in CATEGORY_METRICS:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"Unknown category {category}.",
            f"Use one of: {', '.join(CATEGORY_METRICS)}.",
        )
    metrics = CATEGORY_METRICS[category] if category else SUMMARY_METRICS
    return read_channel_metrics(clients.cloudwatch, channel_id, metrics, recent_window(hours_back))


def check_channel_issues(
    clients: MediaLiveClients, channel_id: str, hours_back: int
) -> ChannelHealthReport:
    window = recent_window(hours_back)
    channel = describe_channel(clients.medialive, channel_id)
    context = ChannelContext(channel.channel_class, channel.output_locking_mode)
    series = read_channel_metrics(clients.cloudwatch, channel_id, ALL_METRICS, window)
    return identify_channel_issues(channel_id, series, context)


def build_metrics_table(
    clients: MediaLiveClients, channel_id: str, hours_back: int
) -> list[MetricRow]:
    wanted = tuple(dict.fromkeys(m for metrics in TABLE_METRICS.values() for m in metrics))
    window = recent_window(hours_back)
    series = read_channel_metrics(clients.cloudwatch, channel_id, wanted, window)
    rows = [
        MetricRow(timestamp=t, category=category, metric=s.metric, pipeline=s.pipeline, value=v)
        for category, metrics in TABLE_METRICS.items()
        for s in series
        if s.metric in metrics
        for t, v in zip(s.timestamps, s.values, strict=True)
    ]
    return sorted(rows, key=lambda row: row.timestamp)
