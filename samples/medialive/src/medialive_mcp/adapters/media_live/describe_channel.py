"""Describe one MediaLive channel: state, inputs and the active input per pipeline."""

from typing import Any

from media_ops_contracts.call_aws_operation import call_aws_operation
from medialive_mcp.adapters.media_live.media_live_records import (
    ChannelDetails,
    ChannelState,
    PipelineDetail,
)


def describe_channel(medialive: Any, channel_id: str) -> ChannelDetails:
    channel = call_aws_operation(medialive, "describe_channel", ChannelId=channel_id)
    encoder = channel.get("EncoderSettings", {})
    return ChannelDetails(
        channel_id=channel.get("Id", channel_id),
        name=channel.get("Name", ""),
        state=ChannelState(channel["State"]),
        pipelines_running=channel.get("PipelinesRunningCount", 0),
        channel_class=channel.get("ChannelClass"),
        output_locking_mode=encoder.get("GlobalConfiguration", {}).get("OutputLockingMode"),
        input_attachments=[
            attachment["InputAttachmentName"] for attachment in channel.get("InputAttachments", [])
        ],
        output_groups=[
            group["Name"] for group in encoder.get("OutputGroups", []) if group.get("Name")
        ],
        audio_descriptions=[
            audio["Name"] for audio in encoder.get("AudioDescriptions", []) if audio.get("Name")
        ],
        pipelines=[
            PipelineDetail(
                pipeline_id=str(pipeline.get("PipelineId", index)),
                active_input_attachment=pipeline.get("ActiveInputAttachmentName"),
            )
            for index, pipeline in enumerate(channel.get("PipelineDetails", []))
        ],
    )
