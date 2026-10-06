"""Read MediaLive channel metrics for both pipelines with one GetMetricData call.

Each metric is queried with the dimension set and statistic MediaLive publishes it with
(domain/metric_catalog.py). Metrics broken down by output group or audio description get
one query per name the channel defines; without such names they are skipped, not queried
empty. DroppedFrames and SvqTime are per pipeline and Region: region-wide, not per channel.
"""

import itertools
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from media_ops_contracts.call_aws_operation import call_aws_operation
from medialive_mcp.domain.metric_catalog import (
    CHANNEL_CONFIGURED_DIMENSIONS,
    CHANNEL_DIMENSIONS,
    DEFAULT_STATISTIC,
    DIMENSIONS_BY_METRIC,
    STATISTIC_BY_METRIC,
)
from medialive_mcp.domain.metric_series import MetricSeries

PIPELINES = ("0", "1")
PERIOD_SECONDS = 300


@dataclass(frozen=True)
class MetricScope:
    """Dimension values that come from the deployment and the channel's configuration."""

    region: str = ""
    output_groups: tuple[str, ...] = ()
    audio_descriptions: tuple[str, ...] = ()


NO_SCOPE = MetricScope()


@dataclass(frozen=True)
class MetricQuery:
    metric: str
    pipeline: str
    dimensions: dict[str, str]  # every dimension of the query, ChannelId included


def read_channel_metrics(
    cloudwatch: Any,
    channel_id: str,
    metrics: tuple[str, ...],
    window: tuple[datetime, datetime],
    scope: MetricScope = NO_SCOPE,
) -> list[MetricSeries]:
    """One value per 5 minutes; series are oldest-first. Missing data gives an empty series."""
    queries = {
        query_id(query, index): query
        for metric in dict.fromkeys(metrics)
        for pipeline in PIPELINES
        for index, query in enumerate(plan_queries(metric, pipeline, channel_id, scope))
    }
    collected: dict[str, list[tuple[datetime, float]]] = {key: [] for key in queries}
    next_token = None
    while queries:
        page = call_aws_operation(
            cloudwatch,
            "get_metric_data",
            MetricDataQueries=[metric_query(key, query) for key, query in queries.items()],
            StartTime=window[0],
            EndTime=window[1],
            **({"NextToken": next_token} if next_token else {}),
        )
        for result in page.get("MetricDataResults", []):
            if result["Id"] in collected:
                points = zip(result.get("Timestamps", []), result.get("Values", []), strict=False)
                collected[result["Id"]].extend(points)
        next_token = page.get("NextToken")
        if not next_token:
            break
    return [to_series(queries[key], points) for key, points in collected.items()]


def plan_queries(
    metric: str, pipeline: str, channel_id: str, scope: MetricScope
) -> list[MetricQuery]:
    """Every dimension combination the metric is published with, for one pipeline."""
    choices = {
        "ChannelId": (channel_id,),
        "Pipeline": (pipeline,),
        "Region": (scope.region,) if scope.region else (),
        "OutputGroupName": scope.output_groups,
        "AudioDescriptionName": scope.audio_descriptions,
    }
    names = DIMENSIONS_BY_METRIC.get(metric, CHANNEL_DIMENSIONS)
    return [
        MetricQuery(metric, pipeline, dict(zip(names, values, strict=True)))
        for values in itertools.product(*(choices[name] for name in names))
    ]


def query_id(query: MetricQuery, index: int) -> str:
    """`input_loss_seconds_p0`; a broken-down metric adds `_d<n>` per dimension value."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", query.metric).lower()
    broken_down = CHANNEL_CONFIGURED_DIMENSIONS.intersection(query.dimensions)
    suffix = f"_d{index}" if broken_down else ""
    return f"{snake}_p{query.pipeline}{suffix}"


def metric_query(key: str, query: MetricQuery) -> dict:
    return {
        "Id": key,
        "MetricStat": {
            "Metric": {
                "Namespace": "AWS/MediaLive",
                "MetricName": query.metric,
                "Dimensions": [{"Name": n, "Value": v} for n, v in query.dimensions.items()],
            },
            "Period": PERIOD_SECONDS,
            "Stat": STATISTIC_BY_METRIC.get(query.metric, DEFAULT_STATISTIC),
        },
        "ReturnData": True,
    }


def to_utc(timestamp: datetime | str) -> datetime:
    """boto3 returns local-offset datetimes; every tool reports UTC (serialized with Z)."""
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return timestamp.astimezone(UTC)


def to_series(query: MetricQuery, points: list) -> MetricSeries:
    ordered = sorted((to_utc(t), v) for t, v in points)
    extra = {n: v for n, v in query.dimensions.items() if n not in CHANNEL_DIMENSIONS}
    return MetricSeries(
        metric=query.metric,
        pipeline=query.pipeline,
        statistic=STATISTIC_BY_METRIC.get(query.metric, DEFAULT_STATISTIC),
        dimensions=extra,
        timestamps=[t for t, _ in ordered],
        values=[v for _, v in ordered],
    )
