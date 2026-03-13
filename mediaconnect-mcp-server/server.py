#!/usr/bin/env python3
"""AWS Elemental MediaConnect MCP Server"""
from fastmcp import FastMCP
from tools.flows import FlowManager
from tools.thumbnails import ThumbnailAnalyzer
from tools.monitoring.coordinator import MonitoringCoordinator

# Initialize MCP server
mcp = FastMCP("MediaConnect MCP Server")

# Initialize managers
flow_manager = FlowManager()
thumbnail_analyzer = ThumbnailAnalyzer()
monitoring_coordinator = MonitoringCoordinator()

@mcp.tool()
def list_flows() -> dict:
    """List all MediaConnect flows"""
    return flow_manager.list_flows()

@mcp.tool()
def describe_flow(flow_arn: str) -> dict:
    """Describe a specific MediaConnect flow by ARN with EventBridge-style health monitoring"""
    return flow_manager.describe_flow(flow_arn)

@mcp.tool()
def start_flow(flow_arn: str) -> dict:
    """Start a MediaConnect flow"""
    return flow_manager.start_flow(flow_arn)

@mcp.tool()
def stop_flow(flow_arn: str) -> dict:
    """Stop a MediaConnect flow"""
    return flow_manager.stop_flow(flow_arn)

@mcp.tool()
def describe_flow_thumbnail(flow_arn: str) -> dict:
    """Get the current thumbnail from a MediaConnect flow and analyze it with Claude to provide a description"""
    return thumbnail_analyzer.describe_flow_thumbnail(flow_arn)

@mcp.tool()
def describe_flow_source_metadata(flow_arn: str) -> dict:
    """Get detailed source metadata for a MediaConnect flow including transport stream and program details"""
    return flow_manager.describe_flow_source_metadata(flow_arn)

# Comprehensive monitoring
@mcp.tool()
def get_all_metrics(flow_arn: str, hours_back: int = 1) -> dict:
    """Get all available CloudWatch metrics organized by category (flow, source, output, media, content quality)"""
    return monitoring_coordinator.get_all_metrics(flow_arn, hours_back)

# Category-specific monitoring
@mcp.tool()
def get_flow_health_metrics(flow_arn: str, hours_back: int = 1) -> dict:
    """Get flow health specific metrics"""
    return monitoring_coordinator.get_category_metrics('flow_health', flow_arn, hours_back)

@mcp.tool()
def get_source_health_metrics(flow_arn: str, hours_back: int = 1) -> dict:
    """Get source health specific metrics"""
    return monitoring_coordinator.get_category_metrics('source_health', flow_arn, hours_back)

@mcp.tool()
def get_output_health_metrics(flow_arn: str, hours_back: int = 1) -> dict:
    """Get output health specific metrics"""
    return monitoring_coordinator.get_category_metrics('output_health', flow_arn, hours_back)

@mcp.tool()
def get_media_health_metrics(flow_arn: str, hours_back: int = 1) -> dict:
    """Get media health specific metrics (jitter, latency, drops, connections)"""
    return monitoring_coordinator.get_category_metrics('media_health', flow_arn, hours_back)

@mcp.tool()
def get_content_quality_metrics(flow_arn: str, hours_back: int = 1) -> dict:
    """Get content quality specific metrics (black frames, frozen frames, missing streams)"""
    return monitoring_coordinator.get_category_metrics('content_quality', flow_arn, hours_back)

@mcp.tool()
def check_flow_issues(flow_arn: str, hours_back: int = 24) -> dict:
    """Check for issues in a MediaConnect flow over the specified time period"""
    return monitoring_coordinator.check_flow_issues(flow_arn, hours_back)

@mcp.tool()
def get_metrics_table(flow_arn: str, hours_back: int = 6) -> dict:
    """Get flow metrics in tabular format suitable for generating graphs"""
    return monitoring_coordinator.get_metrics_table(flow_arn, hours_back)

if __name__ == "__main__":
    mcp.run()
