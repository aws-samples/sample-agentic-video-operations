"""Sample a flow's source thumbnail, score the window, and check it against the transport.

MediaConnect pictures one source per flow (DescribeFlowSourceThumbnail), so the flow gets
one window and one finding. The flow is never HEALTHY without thumbnails and a trusted
vision verdict, and an independent transport or content-quality signal that contradicts
the picture caps it at UNVERIFIED (fuse_with_telemetry, extend_the_hub.md §8).
"""

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from media_ops_contracts.tool_failure import ToolFailure
from media_ops_video_quality.assess_window import (
    Status,
    VisionScores,
    VisionStatus,
    WindowAssessment,
    assess_window,
)
from media_ops_video_quality.fuse_with_telemetry import (
    SEVERITY,
    EncoderSignals,
    QualityFinding,
    SignalReading,
    fuse_with_telemetry,
)
from media_ops_video_quality.score_with_vision import score_with_vision
from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    FlowMetrics,
    MetricCategory,
    read_flow_metrics,
)
from mediaconnect_mcp.adapters.media_connect.read_source_monitoring import (
    SourceMonitoring,
    read_source_monitoring,
)
from mediaconnect_mcp.adapters.media_connect.sample_flow_frames import (
    SampledFlow,
    sample_flow_frames,
)
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import MediaConnectClients

TELEMETRY_HOURS = 1  # read_flow_metrics' smallest window


class FlowVisualQuality(BaseModel):
    flow_arn: str
    window_seconds: int
    status: Status  # fused: the picture, capped at UNVERIFIED by any contradicting signal
    pictured_source: str | None  # the flow's source; MediaConnect pictures one per flow
    sources: list[str]
    assessment: WindowAssessment
    finding: QualityFinding
    note: str | None = None
    telemetry_note: str | None = None
    method: str = (
        "no-reference measurements per frame (sharpness, blockiness estimate, luma, change) "
        "plus one vision-model rubric, checked against the flow's content-quality and "
        "source-connection metrics"
    )


def assess_flow_visual_quality(
    clients: MediaConnectClients,
    flow_arn: str,
    *,
    frames: int,
    window_seconds: int,
    vision_model_id: str | None,
    sleep: Callable[[float], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FlowVisualQuality:
    monitoring = read_source_monitoring(clients.mediaconnect, flow_arn)
    sampled = sample_or_explain(clients, monitoring, frames, window_seconds, sleep, now)
    vision: VisionScores | None = None
    status: VisionStatus = "not_requested"  # the operator chose no model: not a failure
    if vision_model_id is not None:
        vision, status = score_with_vision(
            clients.bedrock, vision_model_id, [f.jpeg for f in sampled.frames]
        )
    assessment = assess_window(
        sampled.frames, requested_frames=frames, vision=vision, vision_status=status
    )
    signals, telemetry_note = read_signals(clients, monitoring, now())
    finding = fuse_with_telemetry(monitoring.source_name or "source", assessment, signals)
    note, fused = None, finding.status
    if not sampled.frames:
        note = (
            f"no thumbnails: {sampled.unavailable_reason or 'none returned'}. Enable source "
            "thumbnails in the flow's source monitoring, or start the flow."
        )
    elif sampled.unavailable_reason:
        # The frames before the outage are measured, but the picture now is unknown.
        fused = max(fused, Status.UNVERIFIED, key=SEVERITY.index)
        note = (
            f"the window ended without thumbnails: {sampled.unavailable_reason}. The earlier "
            "frames are measured; the picture's current state is unknown."
        )
    return FlowVisualQuality(
        flow_arn=monitoring.flow_arn,
        window_seconds=window_seconds,
        status=fused,
        pictured_source=monitoring.source_name,
        sources=monitoring.source_names,
        assessment=assessment,
        finding=finding,
        note=note,
        telemetry_note=telemetry_note,
    )


def sample_or_explain(
    clients: MediaConnectClients,
    monitoring: SourceMonitoring,
    frames: int,
    window_seconds: int,
    sleep: Callable[[float], None],
    now: Callable[[], datetime],
) -> SampledFlow:
    """Poll only when a thumbnail can exist; otherwise say why there is none."""
    if monitoring.thumbnails is False:
        return SampledFlow(
            frames=[],
            unavailable_reason="source thumbnails are disabled (SourceMonitoringConfig)",
        )
    if monitoring.flow_state not in (None, "ACTIVE"):
        return SampledFlow(frames=[], unavailable_reason=f"the flow is {monitoring.flow_state}")
    return sample_flow_frames(
        clients.mediaconnect,
        monitoring.flow_arn,
        frames=frames,
        window_seconds=window_seconds,
        sleep=sleep,
        now=now,
    )


def read_signals(
    clients: MediaConnectClients, monitoring: SourceMonitoring, at: datetime
) -> tuple[EncoderSignals, str | None]:
    """The flow's own signals over the last hour; every one unknown on a read failure."""
    note = None
    series: dict[str, list[float]] = {}
    try:
        for category in (MetricCategory.CONTENT_QUALITY, MetricCategory.SOURCE_HEALTH):
            metrics: FlowMetrics = read_flow_metrics(
                clients.cloudwatch, monitoring.flow_arn, category, TELEMETRY_HOURS, at
            )
            for s in metrics.series:
                if s.points:
                    series[s.name] = [point.value for point in s.points]
    except ToolFailure as failure:
        series = {}
        note = f"flow metrics unavailable ({failure.message}); telemetry counted as unknown"
    if monitoring.content_quality is False:
        # Black/frozen-frame metrics exist only with content quality analysis on.
        for name in ("FrozenFramesBreaching", "BlackFramesBreaching", "VideoStreamMissing"):
            series.pop(name, None)
    frozen = peak(series, "FrozenFramesBreaching")
    black = peak(series, "BlackFramesBreaching")
    disconnections = total(series, "SourceDisconnections")
    connected = lowest(series, "SourceConnected")
    video_missing = peak(series, "VideoStreamMissing")
    interruptions = [
        value > 0 for value in (disconnections, video_missing) if value is not None
    ] + ([connected == 0] if connected is not None else [])
    signals = EncoderSignals(
        source_id=monitoring.source_name or "source",
        window_minutes=TELEMETRY_HOURS * 60,
        freeze=SignalReading(name="FrozenFramesBreaching", detected=positive(frozen)),
        black=SignalReading(name="BlackFramesBreaching", detected=positive(black)),
        interrupted=SignalReading(
            name="SourceDisconnections/SourceConnected/VideoStreamMissing",
            detected=any(interruptions) if interruptions else None,
        ),
        interruption_phrase="source disconnections or a missing video stream",
        no_interruption_phrase="no source disconnections, video stream present",
        unknown_input_phrase="no source-connection or video-stream data",
        readings=[
            ("FrozenFramesBreaching max", frozen),
            ("BlackFramesBreaching max", black),
            ("SourceDisconnections total", disconnections),
            ("SourceConnected min", connected),
            ("VideoStreamMissing max", video_missing),
            ("SourcePacketLossPercent max", peak(series, "SourcePacketLossPercent")),
        ],
        resource_term="flow",
        # The thumbnail is of the source as it arrives, so a bad picture is upstream.
        picture_location="in the source itself, upstream of MediaConnect",
        failover_phrase=(
            "check the upstream encoder, or move outputs to the flow's other source or a backup "
            "flow"
        ),
        active_input=monitoring.source_name,
    )
    return signals, note


def peak(series: dict[str, list[float]], name: str) -> float | None:
    return max(series[name]) if name in series else None


def lowest(series: dict[str, list[float]], name: str) -> float | None:
    return min(series[name]) if name in series else None


def total(series: dict[str, list[float]], name: str) -> float | None:
    return sum(series[name]) if name in series else None


def positive(value: float | None) -> bool | None:
    return None if value is None else value > 0
