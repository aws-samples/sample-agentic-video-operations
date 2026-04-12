"""EML MediaLive tools — plain functions (no @tool decorators).

Composite tools in src/app.py wrap these for agent registration.
"""

from .medialive_tools import (
    current_time,
    list_channels,
    describe_channel,
    start_channel,
    stop_channel,
    get_channel_metrics,
    get_channel_logs,
    describe_channel_thumbnail,
)
from .schedule_tools import (
    describe_schedule,
    create_input_switch_action,
    create_scte35_action,
    create_pause_action,
    create_unpause_action,
    delete_schedule_action,
    create_immediate_input_switch,
)

__all__ = [
    # medialive_tools
    "current_time",
    "list_channels",
    "describe_channel",
    "start_channel",
    "stop_channel",
    "get_channel_metrics",
    "get_channel_logs",
    "describe_channel_thumbnail",
    # schedule_tools
    "describe_schedule",
    "create_input_switch_action",
    "create_scte35_action",
    "create_pause_action",
    "create_unpause_action",
    "delete_schedule_action",
    "create_immediate_input_switch",
]
