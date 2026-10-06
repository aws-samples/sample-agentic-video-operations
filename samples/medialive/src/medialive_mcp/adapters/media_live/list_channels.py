"""List MediaLive channels."""

from typing import Any

from media_ops_contracts.call_aws_operation import collect_pages
from medialive_mcp.adapters.media_live.media_live_records import ChannelState, ChannelSummary


def list_channels(medialive: Any) -> list[ChannelSummary]:
    return [
        ChannelSummary(
            channel_id=channel["Id"],
            name=channel.get("Name", ""),
            state=ChannelState(channel["State"]),
            pipelines_running=channel.get("PipelinesRunningCount", 0),
        )
        for channel in collect_pages(medialive, "list_channels", "Channels")
    ]
