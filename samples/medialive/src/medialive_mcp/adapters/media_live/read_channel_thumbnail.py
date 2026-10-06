"""Read the current thumbnail of one MediaLive pipeline."""

from typing import Any

from pydantic import BaseModel

from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class ChannelThumbnail(BaseModel):
    channel_id: str
    pipeline_id: str
    image_base64: str
    taken_at: str | None = None


def read_channel_thumbnail(medialive: Any, channel_id: str, pipeline_id: str) -> ChannelThumbnail:
    response = call_aws_operation(
        medialive,
        "describe_thumbnails",
        ChannelId=channel_id,
        PipelineId=pipeline_id,
        ThumbnailType="CURRENT_ACTIVE",
    )
    details = response.get("ThumbnailDetails", [])
    thumbnails = details[0].get("Thumbnails", []) if details else []
    body = thumbnails[0].get("Body") if thumbnails else None
    if not body:
        raise ToolFailure(
            FailureKind.RESOURCE_NOT_FOUND,
            f"No thumbnail for channel {channel_id} pipeline {pipeline_id}.",
            "Check that the channel is RUNNING and thumbnails are enabled in its settings.",
        )
    return ChannelThumbnail(
        channel_id=channel_id,
        pipeline_id=pipeline_id,
        image_base64=body,
        taken_at=str(thumbnails[0].get("TimeStamp")) if thumbnails[0].get("TimeStamp") else None,
    )
