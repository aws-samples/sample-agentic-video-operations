"""Read a flow thumbnail and describe it without exposing image bytes."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from mediaconnect_mcp.adapters.bedrock.describe_thumbnail import describe_thumbnail
from mediaconnect_mcp.adapters.media_connect.read_flow_thumbnail import read_flow_thumbnail


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
    model_id: str,
) -> FlowThumbnailDescription:
    """Join the MediaConnect image read to the Bedrock description."""
    thumbnail = read_flow_thumbnail(media_connect, flow_arn)
    description = describe_thumbnail(bedrock, thumbnail.image_base64, model_id)
    return FlowThumbnailDescription(
        flow_arn=thumbnail.flow_arn,
        description=description.text,
        observed_at=thumbnail.observed_at,
        timecode=thumbnail.timecode,
        messages=thumbnail.messages,
    )
