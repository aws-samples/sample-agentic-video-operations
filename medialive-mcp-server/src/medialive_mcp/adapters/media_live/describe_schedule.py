"""List the schedule actions of one MediaLive channel."""

from typing import Any

from media_ops_contracts.call_aws_operation import collect_pages
from medialive_mcp.adapters.media_live.media_live_records import ScheduleActionSummary


def describe_schedule(medialive: Any, channel_id: str) -> list[ScheduleActionSummary]:
    actions = collect_pages(medialive, "describe_schedule", "ScheduleActions", ChannelId=channel_id)
    return [_summarize_action(action) for action in actions]


def _summarize_action(action: dict) -> ScheduleActionSummary:
    settings = action.get("ScheduleActionSettings", {})
    start = action.get("ScheduleActionStartSettings", {})
    if "FixedModeScheduleActionStartSettings" in start:
        start_text = start["FixedModeScheduleActionStartSettings"].get("Time", "")
    elif "FollowModeScheduleActionStartSettings" in start:
        start_text = "follow " + start["FollowModeScheduleActionStartSettings"].get(
            "FollowPoint", ""
        )
    else:
        start_text = "immediate"
    return ScheduleActionSummary(
        action_name=action.get("ActionName", ""),
        action_type=next(iter(settings), "Unknown"),
        start=start_text,
        input_attachment=settings.get("InputSwitchSettings", {}).get(
            "InputAttachmentNameReference"
        ),
    )
