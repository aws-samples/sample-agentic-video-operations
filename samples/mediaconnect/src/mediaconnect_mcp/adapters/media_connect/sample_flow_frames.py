"""Sample a flow's source thumbnail over a window (DescribeFlowSourceThumbnail).

MediaConnect returns one thumbnail per flow: of the flow's source, not one per source of a
failover flow. Polls `frames` times across `window_seconds` and keeps one frame per
distinct thumbnail Timestamp. A thumbnail that is not available (thumbnails disabled, the
flow not active, or a source the service cannot picture) yields no frames and the
service's own reason, never an error: the assessment then reports UNVERIFIED with it.
When the service refuses the call (BadRequest, NotFound), that answer is conclusive:
sampling stops after that one read, with no more calls and no waits.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.assess_window import SampledFrame
from media_ops_video_quality.decode_thumbnail import decode_thumbnail
from media_ops_video_quality.sampling_limits import WINDOW_REFUSAL, window_is_allowed
from mediaconnect_mcp.adapters.media_connect.read_flow_thumbnail import (
    ThumbnailUnavailable,
    read_flow_thumbnail,
)


class SampledFlow(BaseModel):
    frames: list[SampledFrame]
    # Why the window ended without a thumbnail, if it did: set by a poll with no picture,
    # cleared by a later one with a picture. Frames before an ending outage are kept.
    unavailable_reason: str | None = None


def sample_flow_frames(
    media_connect: Any,
    flow_arn: str,
    *,
    frames: int,
    window_seconds: int,
    sleep: Callable[[float], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SampledFlow:
    if not window_is_allowed(frames, window_seconds):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST, WINDOW_REFUSAL, "Use the defaults, or a shorter window."
        )
    by_time: dict[str, SampledFrame] = {}
    reason = None
    interval = window_seconds / (frames - 1)
    for tick in range(frames):
        try:
            thumbnail = read_flow_thumbnail(media_connect, flow_arn)
        except ThumbnailUnavailable as unavailable:
            reason = unavailable.message
            if unavailable.conclusive:
                break
        else:
            taken_at = thumbnail.observed_at or now()
            if taken_at.tzinfo is None:
                taken_at = taken_at.replace(tzinfo=UTC)
            frame = SampledFrame(taken_at=taken_at, jpeg=decode_thumbnail(thumbnail.image_base64))
            by_time.setdefault(taken_at.isoformat(), frame)
            reason = None
        if tick < frames - 1:
            sleep(interval)
    return SampledFlow(frames=list(by_time.values()), unavailable_reason=reason)
