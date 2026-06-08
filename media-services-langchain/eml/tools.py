"""LangChain @tool wrappers around existing medialive-mcp-server implementations.

These import the pure-function implementations from src/tools/ (copied into the
container from medialive-mcp-server/src/) and expose them as LangChain tools.
The domain logic is NOT duplicated — only the framework adapter layer lives here.

Container layout:
  /app/src/           ← medialive-mcp-server/src/ (tools, monitoring, utils)
  /app/eml/           ← this agent's code
  /app/shared/        ← shared module
"""

from typing import Optional
from langchain_core.tools import tool

from src.tools import (
    list_channels,
    describe_channel,
    start_channel,
    stop_channel,
    get_channel_metrics,
    get_channel_logs,
    describe_schedule,
    create_input_switch_action,
    create_immediate_input_switch,
)
from src.monitoring.coordinator import MonitoringCoordinator

_monitoring = MonitoringCoordinator()


@tool
def eml_list_channels() -> str:
    """List all MediaLive channels with IDs, ARNs, and state."""
    return list_channels()


@tool
def eml_describe_channel(channel_id: Optional[str] = None) -> str:
    """Get detailed channel configuration, input attachments, and pipeline status."""
    return describe_channel(channel_id)


@tool
def eml_start_channel(channel_id: Optional[str] = None) -> str:
    """Start a MediaLive channel. DESTRUCTIVE — requires approval."""
    return start_channel(channel_id)


@tool
def eml_stop_channel(channel_id: Optional[str] = None) -> str:
    """Stop a running MediaLive channel. DESTRUCTIVE — requires approval."""
    return stop_channel(channel_id)


@tool
def eml_get_metrics(channel_id: Optional[str] = None, hours_back: int = 1) -> str:
    """Get CloudWatch metrics for a channel (frame rate, network, fill, alerts)."""
    return get_channel_metrics(channel_id, hours_back)


@tool
def eml_get_logs(channel_id: Optional[str] = None, hours_back: int = 1) -> str:
    """Get recent CloudWatch log events for a channel."""
    return get_channel_logs(channel_id, hours_back)


@tool
def eml_describe_schedule(channel_id: Optional[str] = None) -> str:
    """List all schedule actions for a channel."""
    return describe_schedule(channel_id)


@tool
def eml_input_switch(channel_id: str, action_name: str, input_attachment_name: str, start_time: str) -> str:
    """Schedule a timed input switch. DESTRUCTIVE — requires approval."""
    return create_input_switch_action(channel_id, action_name, input_attachment_name, start_time)


@tool
def eml_immediate_input_switch(channel_id: str, action_name: str, input_attachment_name: str) -> str:
    """Immediately switch the active input. DESTRUCTIVE — requires approval."""
    return create_immediate_input_switch(channel_id, action_name, input_attachment_name)


@tool
def eml_check_issues(channel_id: str, hours_back: int = 24) -> str:
    """Cross-category issue scan with HIGH/MEDIUM severity classification."""
    return _monitoring.check_channel_issues(channel_id, hours_back)


ALL_TOOLS = [
    eml_list_channels,
    eml_describe_channel,
    eml_start_channel,
    eml_stop_channel,
    eml_get_metrics,
    eml_get_logs,
    eml_describe_schedule,
    eml_input_switch,
    eml_immediate_input_switch,
    eml_check_issues,
]
