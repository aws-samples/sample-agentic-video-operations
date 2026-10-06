"""Read a category of MediaConnect CloudWatch metrics in one batch."""

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class MetricCategory(StrEnum):
    FLOW_HEALTH = "flow_health"
    SOURCE_HEALTH = "source_health"
    OUTPUT_HEALTH = "output_health"
    MEDIA_HEALTH = "media_health"
    CONTENT_QUALITY = "content_quality"


METRICS_BY_CATEGORY = {
    MetricCategory.FLOW_HEALTH: (
        "ARQRecovered",
        "BitRate",
        "Connected",
        "Disconnections",
        "DroppedPackets",
        "NotRecoveredPackets",
        "PacketLossPercent",
        "RoundTripTime",
        "PATError",
        "PMTError",
        "TSSyncLoss",
    ),
    MetricCategory.SOURCE_HEALTH: (
        "SourceARQRecovered",
        "SourceBitRate",
        "SourceConnected",
        "SourceDisconnections",
        "SourceDroppedPackets",
        "SourceNotRecoveredPackets",
        "SourcePacketLossPercent",
        "SourceRoundTripTime",
        "SourceMergeStatusWarnMismatch",
        "SourceMergeStatusWarnSolo",
    ),
    MetricCategory.OUTPUT_HEALTH: (
        "ConnectedOutputs",
        "OutputBitrate",
        "OutputConnected",
        "OutputDisconnections",
        "OutputNotRecoveredPackets",
        "OutputDroppedPayloads",
        "OutputLatePayloads",
        "OutputTotalPackets",
    ),
    MetricCategory.MEDIA_HEALTH: (
        "ConnectionAttempts",
        "ConsecutiveDrops",
        "ConsecutiveNotRecovered",
        "SourceJitter",
        "SourceLatency",
        "SourceUptime",
    ),
    MetricCategory.CONTENT_QUALITY: (
        "AudioStreamMissing",
        "BlackFramesBreaching",
        "FrozenFramesBreaching",
        "SilentAudioBreaching",
        "TimecodePresent",
        "VideoStreamMissing",
    ),
}


class MetricPoint(BaseModel):
    at: datetime
    value: float


class MetricSeries(BaseModel):
    name: str
    label: str
    status: str
    points: list[MetricPoint]


class FlowMetrics(BaseModel):
    flow_arn: str
    category: MetricCategory
    hours_back: int
    series: list[MetricSeries]


def read_flow_metrics(
    cloudwatch: Any,
    flow_arn: str,
    category: MetricCategory,
    hours_back: int,
    now: datetime,
) -> FlowMetrics:
    """Return timestamped metric series for one operational category."""
    if not 1 <= hours_back <= 168:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "hours_back must be between 1 and 168.",
            "Use a window from one hour to seven days.",
        )
    if now.tzinfo is None or now.utcoffset() is None:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "Metric reads require a timezone-aware current time.",
            "Pass datetime.now(UTC).",
        )
    names = METRICS_BY_CATEGORY[category]
    queries = [_build_query(index, name, flow_arn) for index, name in enumerate(names)]
    try:
        response = cloudwatch.get_metric_data(
            MetricDataQueries=queries,
            StartTime=now - timedelta(hours=hours_back),
            EndTime=now,
            ScanBy="TimestampAscending",
        )
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation="Read MediaConnect metrics") from error
    names_by_id = {query["Id"]: name for query, name in zip(queries, names, strict=True)}
    return FlowMetrics(
        flow_arn=flow_arn,
        category=category,
        hours_back=hours_back,
        series=[
            _translate_result(result, names_by_id)
            for result in response.get("MetricDataResults", [])
            if result.get("Id") in names_by_id
        ],
    )


def _build_query(index: int, name: str, flow_arn: str) -> dict[str, Any]:
    return {
        "Id": f"m{index}_{re.sub(r'[^a-z0-9]', '', name.lower())}",
        "MetricStat": {
            "Metric": {
                "Namespace": "AWS/MediaConnect",
                "MetricName": name,
                "Dimensions": [{"Name": "FlowARN", "Value": flow_arn}],
            },
            "Period": 300,
            "Stat": _statistic_for(name),
        },
        "ReturnData": True,
    }


def _statistic_for(name: str) -> str:
    averaged = ("BitRate", "Bitrate", "Percent", "Jitter", "Latency", "RoundTripTime")
    return "Average" if any(fragment in name for fragment in averaged) else "Sum"


def _translate_result(result: dict[str, Any], names_by_id: dict[str, str]) -> MetricSeries:
    timestamps = result.get("Timestamps", [])
    values = result.get("Values", [])
    return MetricSeries(
        name=names_by_id.get(result.get("Id", ""), result.get("Label", "unknown")),
        label=result.get("Label", ""),
        status=result.get("StatusCode", "Complete"),
        points=[
            MetricPoint(at=timestamp, value=float(value))
            for timestamp, value in zip(timestamps, values, strict=False)
        ],
    )
