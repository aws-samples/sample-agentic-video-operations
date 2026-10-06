"""Read the current thumbnail bytes for one MediaConnect flow."""

from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class FlowThumbnail(BaseModel):
    flow_arn: str
    image_base64: str
    observed_at: datetime | None = None
    timecode: str | None = None
    messages: list[str]


def read_flow_thumbnail(media_connect: Any, flow_arn: str) -> FlowThumbnail:
    """Return the current JPEG thumbnail without exposing it as tool output."""
    try:
        response = media_connect.describe_flow_source_thumbnail(FlowArn=flow_arn)
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation="Read MediaConnect flow thumbnail") from error
    details = response.get("ThumbnailDetails", {})
    image = details.get("Thumbnail")
    if not image:
        raise ToolFailure(
            FailureKind.RESOURCE_NOT_FOUND,
            "No thumbnail is available for this flow.",
            "Confirm the flow is active and source thumbnails are enabled.",
        )
    return FlowThumbnail(
        flow_arn=details.get("FlowArn", flow_arn),
        image_base64=image,
        observed_at=details.get("Timestamp"),
        timecode=details.get("Timecode"),
        messages=details.get("ThumbnailMessages", []),
    )
