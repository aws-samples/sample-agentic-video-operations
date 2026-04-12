#!/usr/bin/env python3
"""AWS Elemental MediaLive MCP Server"""
from typing import Optional
from fastmcp import FastMCP
from src.tools import (
    list_channels,
    describe_channel,
    start_channel,
    stop_channel,
    get_channel_metrics,
    get_channel_logs,
    describe_channel_thumbnail,
    describe_schedule,
    create_input_switch_action,
    create_scte35_action,
    create_pause_action,
    create_unpause_action,
    delete_schedule_action,
    create_immediate_input_switch,
)
from src.monitoring.coordinator import MonitoringCoordinator

# Initialize MCP server
mcp = FastMCP("MediaLive MCP Server")

# Initialize monitoring coordinator
monitoring_coordinator = MonitoringCoordinator()


# --- Migrated channel tools ---

@mcp.tool()
def mcp_list_channels() -> str:
    """List all MediaLive channels with their IDs, ARNs, and current state"""
    return list_channels()


@mcp.tool()
def mcp_describe_channel(channel_id: Optional[str] = None) -> str:
    """Get detailed channel configuration, input attachments, and pipeline status"""
    return describe_channel(channel_id)


@mcp.tool()
def mcp_start_channel(channel_id: Optional[str] = None) -> str:
    """Start a MediaLive channel to begin encoding and output"""
    return start_channel(channel_id)


@mcp.tool()
def mcp_stop_channel(channel_id: Optional[str] = None) -> str:
    """Stop a running MediaLive channel"""
    return stop_channel(channel_id)


@mcp.tool()
def mcp_get_channel_metrics(channel_id: Optional[str] = None, hours_back: int = 1) -> str:
    """Get basic CloudWatch metrics for a MediaLive channel (frame rate, network, fill, alerts)"""
    return get_channel_metrics(channel_id, hours_back)


@mcp.tool()
def mcp_get_channel_logs(channel_id: Optional[str] = None, hours_back: int = 1) -> str:
    """Get recent CloudWatch log events for a MediaLive channel"""
    return get_channel_logs(channel_id, hours_back)


@mcp.tool()
def mcp_describe_channel_thumbnail(channel_id: Optional[str] = None, pipeline_id: str = "0") -> dict:
    """Capture and analyze the current channel thumbnail using Bedrock vision"""
    return describe_channel_thumbnail(channel_id, pipeline_id)


# --- Migrated schedule tools ---

@mcp.tool()
def mcp_describe_schedule(channel_id: Optional[str] = None) -> str:
    """List all schedule actions for a MediaLive channel"""
    return describe_schedule(channel_id)


@mcp.tool()
def mcp_create_input_switch_action(
    channel_id: Optional[str] = None,
    action_name: str = "",
    input_attachment_name: str = "",
    start_time: str = "",
) -> str:
    """Schedule a timed input switch on a MediaLive channel"""
    return create_input_switch_action(channel_id, action_name, input_attachment_name, start_time)


@mcp.tool()
def mcp_create_scte35_action(
    channel_id: Optional[str] = None,
    action_name: str = "",
    start_time: str = "",
    splice_event_id: int = 0,
    duration: Optional[int] = None,
) -> str:
    """Schedule a SCTE-35 splice insert for ad signaling on a MediaLive channel"""
    return create_scte35_action(channel_id, action_name, start_time, splice_event_id, duration)


@mcp.tool()
def mcp_create_pause_action(
    channel_id: Optional[str] = None,
    action_name: str = "",
    start_time: str = "",
    pipeline_id: str = "PIPELINE_0",
) -> str:
    """Schedule a pipeline pause on a MediaLive channel"""
    return create_pause_action(channel_id, action_name, start_time, pipeline_id)


@mcp.tool()
def mcp_create_unpause_action(
    channel_id: Optional[str] = None,
    action_name: str = "",
    start_time: str = "",
    pipeline_id: str = "PIPELINE_0",
) -> str:
    """Schedule a pipeline unpause on a MediaLive channel"""
    return create_unpause_action(channel_id, action_name, start_time, pipeline_id)


@mcp.tool()
def mcp_delete_schedule_action(channel_id: Optional[str] = None, action_name: str = "") -> str:
    """Delete a schedule action from a MediaLive channel"""
    return delete_schedule_action(channel_id, action_name)


@mcp.tool()
def mcp_create_immediate_input_switch(
    channel_id: Optional[str] = None,
    action_name: str = "",
    input_attachment_name: str = "",
) -> str:
    """Immediately switch the active input on a MediaLive channel"""
    return create_immediate_input_switch(channel_id, action_name, input_attachment_name)


# --- Monitoring tools (new, delegating to coordinator) ---

@mcp.tool()
def mcp_get_all_metrics(channel_id: str, hours_back: int = 1) -> dict:
    """Get all CloudWatch metrics across all 5 categories for a MediaLive channel"""
    return monitoring_coordinator.get_all_metrics(channel_id, hours_back)


@mcp.tool()
def mcp_get_channel_health_metrics(channel_id: str, hours_back: int = 1) -> dict:
    """Get channel health metrics: alerts, pipeline lock, fill, frame rate, dropped frames"""
    return monitoring_coordinator.get_category_metrics('channel_health', channel_id, hours_back)


@mcp.tool()
def mcp_get_input_health_metrics(channel_id: str, hours_back: int = 1) -> dict:
    """Get input health metrics: network in, input loss, RTP packets, FEC recovery"""
    return monitoring_coordinator.get_category_metrics('input_health', channel_id, hours_back)


@mcp.tool()
def mcp_get_output_health_metrics(channel_id: str, hours_back: int = 1) -> dict:
    """Get output health metrics: network out, active outputs, HTTP errors, audio levels"""
    return monitoring_coordinator.get_category_metrics('output_health', channel_id, hours_back)


@mcp.tool()
def mcp_get_media_health_metrics(channel_id: str, hours_back: int = 1) -> dict:
    """Get media health metrics: timecodes, audio levels, input errors, fill milliseconds"""
    return monitoring_coordinator.get_category_metrics('media_health', channel_id, hours_back)


@mcp.tool()
def mcp_get_content_quality_metrics(channel_id: str, hours_back: int = 1) -> dict:
    """Get content quality metrics: MQCS score, black/freeze frame detection, continuity errors"""
    return monitoring_coordinator.get_category_metrics('content_quality', channel_id, hours_back)


@mcp.tool()
def mcp_check_channel_issues(channel_id: str, hours_back: int = 24) -> dict:
    """Scan all metric categories for issues on a MediaLive channel over the specified period"""
    return monitoring_coordinator.check_channel_issues(channel_id, hours_back)


@mcp.tool()
def mcp_get_metrics_table(channel_id: str, hours_back: int = 6) -> dict:
    """Get channel metrics in tabular format suitable for generating graphs and charts"""
    return monitoring_coordinator.get_metrics_table(channel_id, hours_back)


if __name__ == "__main__":
    mcp.run()
