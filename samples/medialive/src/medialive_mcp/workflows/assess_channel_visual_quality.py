"""Sample both pipelines, measure every frame, score the window once per pipeline, then fuse
the result with the encoder's own signals (MQCS freeze and black, fill frames, input loss)
and the active input into findings.

The channel is never HEALTHY unless every pipeline is: a pipeline without thumbnails, or
without a trusted vision verdict, is UNVERIFIED and keeps the channel from reading healthy.
Telemetry that cannot be read counts as unknown, never as agreement.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.assess_window import (
    SampledFrame,
    Status,
    VisionScores,
    VisionStatus,
    WindowAssessment,
    assess_window,
)
from media_ops_video_quality.fuse_with_telemetry import (
    PipelineTelemetry,
    QualityFinding,
    fuse_with_telemetry,
)
from media_ops_video_quality.score_with_vision import score_with_vision
from medialive_mcp.adapters.media_live.describe_channel import describe_channel
from medialive_mcp.adapters.media_live.media_live_records import ChannelDetails
from medialive_mcp.adapters.media_live.sample_channel_frames import sample_channel_frames
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.domain.metric_series import MetricSeries
from medialive_mcp.workflows.check_channel_health import read_metrics

TELEMETRY = ("MqcsFreezeFrameDetected", "MqcsBlackFrameDetected", "FillMsec", "InputLossSeconds")
TELEMETRY_WINDOW = timedelta(minutes=15)

SEVERITY = [Status.HEALTHY, Status.UNVERIFIED, Status.WARNING, Status.DEGRADED, Status.CRITICAL]


class PipelineVisualQuality(BaseModel):
    pipeline_id: str
    assessment: WindowAssessment
    note: str | None = None


class ChannelVisualQuality(BaseModel):
    channel_id: str
    window_seconds: int
    status: Status  # the worst fused pipeline status, over every pipeline, whatever is asked
    worst_pipeline_id: str
    pipelines: list[PipelineVisualQuality]  # the requested pipeline, or all of them
    findings: list[QualityFinding]  # one per pipeline in `pipelines`
    telemetry_note: str | None = None
    method: str = (
        "no-reference measurements per frame (sharpness, blockiness estimate, luma, change) "
        "plus one vision-model rubric per pipeline window"
    )


def assess_channel_visual_quality(
    clients: MediaLiveClients,
    channel_id: str,
    *,
    pipeline_id: str | None,
    frames: int,
    window_seconds: int,
    vision_model_id: str | None,
    sleep: Callable[[float], None],
) -> ChannelVisualQuality:
    # Every pipeline is sampled in the same fixed order, even when one is asked for: the
    # result does not depend on the request shape (and fixture replay stays in step).
    details = describe_channel(clients.medialive, channel_id)
    pipelines = [p.pipeline_id for p in details.pipelines] or ["0"]
    if pipeline_id is not None and pipeline_id not in pipelines:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"Channel {channel_id} has no pipeline {pipeline_id}.",
            f"Use one of: {', '.join(pipelines)}.",
        )
    sampled = sample_channel_frames(
        clients.medialive, channel_id, pipelines,
        frames=frames, window_seconds=window_seconds, sleep=sleep,
    )  # fmt: skip
    # Every pipeline is scored, in the same order, before any filtering: the channel status
    # is the worst pipeline's whatever was asked, and one pipeline's assessment never
    # depends on whether another was requested.
    results = [
        assess_pipeline(clients, pipeline, sampled[pipeline], frames, vision_model_id)
        for pipeline in pipelines
    ]
    telemetry, note = read_telemetry(clients, channel_id, details)
    findings = [
        fuse_with_telemetry(
            r.pipeline_id,
            r.assessment,
            telemetry.get(r.pipeline_id, PipelineTelemetry(pipeline_id=r.pipeline_id)),
        )
        for r in results
    ]
    # The channel reads the fused status: an encoder contradiction keeps it from HEALTHY.
    worst = max(findings, key=lambda f: SEVERITY.index(f.status))
    wanted = [pipeline_id] if pipeline_id is not None else pipelines
    return ChannelVisualQuality(
        channel_id=channel_id,
        window_seconds=window_seconds,
        status=worst.status,
        worst_pipeline_id=worst.pipeline_id,
        pipelines=[r for r in results if r.pipeline_id in wanted],
        findings=[f for f in findings if f.pipeline_id in wanted],
        telemetry_note=note,
    )


def assess_pipeline(
    clients: MediaLiveClients,
    pipeline: str,
    window: list[SampledFrame],
    frames: int,
    vision_model_id: str | None,
) -> PipelineVisualQuality:
    vision: VisionScores | None = None
    status: VisionStatus = "not_requested"  # the operator chose no model: not a failure
    if vision_model_id is not None:
        vision, status = score_with_vision(
            clients.bedrock, vision_model_id, [f.jpeg for f in window]
        )
    assessment = assess_window(window, requested_frames=frames, vision=vision, vision_status=status)
    note = (
        None
        if window
        else "no thumbnails: enable them in the channel settings, or start the channel"
    )
    return PipelineVisualQuality(pipeline_id=pipeline, assessment=assessment, note=note)


def read_telemetry(
    clients: MediaLiveClients, channel_id: str, details: ChannelDetails
) -> tuple[dict[str, PipelineTelemetry], str | None]:
    """The encoder's signals per pipeline over the last 15 minutes; empty on a read failure."""
    end = datetime.now(UTC)
    try:
        series = read_metrics(
            clients, channel_id, TELEMETRY, (end - TELEMETRY_WINDOW, end), details
        )
    except ToolFailure as failure:
        return {}, f"encoder metrics unavailable ({failure.message}); telemetry counted as unknown"
    active = {p.pipeline_id: p.active_input_attachment for p in details.pipelines}
    telemetry = {}
    for pipeline in active:
        mine = {s.metric: s for s in series if s.pipeline == pipeline}
        telemetry[pipeline] = PipelineTelemetry(
            pipeline_id=pipeline,
            window_minutes=int(TELEMETRY_WINDOW.total_seconds() // 60),
            mqcs_freeze_min=lowest(mine.get("MqcsFreezeFrameDetected")),
            mqcs_black_min=lowest(mine.get("MqcsBlackFrameDetected")),
            fill_msec_max=highest(mine.get("FillMsec")),
            input_loss_seconds=(
                mine["InputLossSeconds"].total if "InputLossSeconds" in mine else None
            ),
            active_input=active[pipeline],
        )
    return telemetry, None


def lowest(series: MetricSeries | None) -> float | None:
    return min(series.values) if series and series.values else None


def highest(series: MetricSeries | None) -> float | None:
    return max(series.values) if series and series.values else None
