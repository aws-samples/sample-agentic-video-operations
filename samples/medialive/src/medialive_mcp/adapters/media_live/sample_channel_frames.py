"""Sample a channel's thumbnails over a window, all requested pipelines in the same ticks.

Polls `frames` times across `window_seconds` and keeps one frame per distinct thumbnail
TimeStamp, so a thumbnail that did not refresh is not counted twice. A pipeline without
thumbnails (disabled in the channel settings, or not running) yields no frames rather than
an error: the assessment then reports it UNVERIFIED with that reason.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.assess_window import SampledFrame
from media_ops_video_quality.decode_thumbnail import decode_thumbnail
from media_ops_video_quality.sampling_limits import WINDOW_REFUSAL, window_is_allowed
from medialive_mcp.adapters.media_live.read_channel_thumbnail import read_channel_thumbnail


def sample_channel_frames(
    medialive: Any,
    channel_id: str,
    pipeline_ids: list[str],
    *,
    frames: int,
    window_seconds: int,
    sleep: Callable[[float], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, list[SampledFrame]]:
    if not window_is_allowed(frames, window_seconds):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST, WINDOW_REFUSAL, "Use the defaults, or a shorter window."
        )
    sampled: dict[str, dict[str, SampledFrame]] = {pipeline: {} for pipeline in pipeline_ids}
    interval = window_seconds / (frames - 1)
    for tick in range(frames):
        for pipeline in pipeline_ids:
            frame = read_one_frame(medialive, channel_id, pipeline, now)
            if frame is not None:
                sampled[pipeline].setdefault(frame.taken_at.isoformat(), frame)
        if tick < frames - 1:
            sleep(interval)
    return {pipeline: list(by_time.values()) for pipeline, by_time in sampled.items()}


def read_one_frame(
    medialive: Any, channel_id: str, pipeline: str, now: Callable[[], datetime]
) -> SampledFrame | None:
    try:
        thumbnail = read_channel_thumbnail(medialive, channel_id, pipeline)
    except ToolFailure as failure:
        if failure.kind is FailureKind.RESOURCE_NOT_FOUND:
            return None  # no thumbnail: disabled, or the pipeline is not producing output
        raise
    taken_at = parse_time(thumbnail.taken_at) or now()
    return SampledFrame(taken_at=taken_at, jpeg=decode_thumbnail(thumbnail.image_base64))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
