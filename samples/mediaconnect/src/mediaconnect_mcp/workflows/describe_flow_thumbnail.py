"""Read a flow thumbnail and describe it without exposing image bytes."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.decode_thumbnail import decode_thumbnail
from media_ops_video_quality.score_with_vision import describe_frame
from mediaconnect_mcp.adapters.media_connect.read_flow_thumbnail import read_flow_thumbnail
from mediaconnect_mcp.prompts.describe_thumbnail_prompt import DESCRIBE_THUMBNAIL_PROMPT


class FlowThumbnailDescription(BaseModel):
    flow_arn: str
    description: str
    observed_at: datetime | None = None
    timecode: str | None = None
    messages: list[str]


def describe_flow_thumbnail(
    media_connect: Any,
    bedrock: Any,
    flow_arn: str,
    model_id: str | None,
) -> FlowThumbnailDescription:
    """Join the MediaConnect image read to the Bedrock description."""
    if not model_id:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "THUMBNAIL_MODEL_ID is not set.",
            "Set THUMBNAIL_MODEL_ID in the root .env (see .env.example).",
        )
    thumbnail = read_flow_thumbnail(media_connect, flow_arn)
    frame = decode_thumbnail(thumbnail.image_base64)
    description = describe_frame(bedrock, model_id, frame, DESCRIBE_THUMBNAIL_PROMPT)
    return FlowThumbnailDescription(
        flow_arn=thumbnail.flow_arn,
        description=description,
        observed_at=thumbnail.observed_at,
        timecode=thumbnail.timecode,
        messages=thumbnail.messages,
    )
