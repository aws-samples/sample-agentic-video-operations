"""Read MediaLive channel metrics for both pipelines with one GetMetricData call."""

import re
from datetime import datetime
from typing import Any

from media_ops_contracts.call_aws_operation import call_aws_operation
from medialive_mcp.domain.metric_series import MetricSeries

PIPELINES = ("0", "1")
PERIOD_SECONDS = 300


def read_channel_metrics(
    cloudwatch: Any, channel_id: str, metrics: tuple[str, ...], window: tuple[datetime, datetime]
) -> list[MetricSeries]:
    """Average per 5 minutes; series are oldest-first. Missing data gives an empty series."""
    queries = {
        _query_id(metric, pipeline): (metric, pipeline)
        for metric in dict.fromkeys(metrics)
        for pipeline in PIPELINES
    }
    collected: dict[str, list[tuple[datetime, float]]] = {query_id: [] for query_id in queries}
    next_token = None
    while True:
        page = call_aws_operation(
            cloudwatch,
            "get_metric_data",
            MetricDataQueries=[_metric_query(i, *queries[i], channel_id) for i in queries],
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
    return [_to_series(*queries[query_id], points) for query_id, points in collected.items()]


def _query_id(metric: str, pipeline: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", metric).lower()
    return f"{snake}_p{pipeline}"


def _metric_query(query_id: str, metric: str, pipeline: str, channel_id: str) -> dict:
    dimensions = [
        {"Name": "ChannelId", "Value": channel_id},
        {"Name": "Pipeline", "Value": pipeline},
    ]
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": "AWS/MediaLive",
                "MetricName": metric,
                "Dimensions": dimensions,
            },
            "Period": PERIOD_SECONDS,
            "Stat": "Average",
        },
        "ReturnData": True,
    }


def _to_series(metric: str, pipeline: str, points: list) -> MetricSeries:
    ordered = sorted(
        (datetime.fromisoformat(str(t).replace("Z", "+00:00")) if isinstance(t, str) else t, v)
        for t, v in points
    )
    return MetricSeries(
        metric=metric,
        pipeline=pipeline,
        timestamps=[t for t, _ in ordered],
        values=[v for _, v in ordered],
    )
