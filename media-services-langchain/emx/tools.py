"""LangChain @tool wrappers around existing mediaconnect-mcp-server implementations.

These import the class-based implementations from tools/ (copied into the
container from mediaconnect-mcp-server/tools/) and expose them as LangChain tools.
The domain logic is NOT duplicated — only the framework adapter layer lives here.

Container layout:
  /app/tools/         ← mediaconnect-mcp-server/tools/ (flows, monitoring, thumbnails)
  /app/emx/           ← this agent's code
  /app/shared/        ← shared module
"""

import json
from langchain_core.tools import tool

from tools.flows import FlowManager
from tools.thumbnails import ThumbnailAnalyzer
from tools.monitoring.coordinator import MonitoringCoordinator

_flow_mgr = FlowManager()
_thumbnails = ThumbnailAnalyzer()
_monitoring = MonitoringCoordinator()


@tool
def emx_list_flows() -> str:
    """List all MediaConnect flows with ARNs, names, and status."""
    result = _flow_mgr.list_flows()
    return json.dumps(result, default=str)


@tool
def emx_describe_flow(flow_arn: str) -> str:
    """Describe a specific MediaConnect flow by ARN with health monitoring."""
    result = _flow_mgr.describe_flow(flow_arn)
    return json.dumps(result, default=str)


@tool
def emx_start_flow(flow_arn: str) -> str:
    """Start a MediaConnect flow. DESTRUCTIVE — requires approval."""
    result = _flow_mgr.start_flow(flow_arn)
    return json.dumps(result, default=str)


@tool
def emx_stop_flow(flow_arn: str) -> str:
    """Stop a MediaConnect flow. DESTRUCTIVE — requires approval."""
    result = _flow_mgr.stop_flow(flow_arn)
    return json.dumps(result, default=str)


@tool
def emx_get_thumbnail(flow_arn: str) -> str:
    """Get AI-powered visual analysis of flow thumbnail via Bedrock."""
    result = _thumbnails.analyze_thumbnail(flow_arn)
    return json.dumps(result, default=str)


@tool
def emx_get_flow_metrics(flow_arn: str, hours_back: int = 1) -> str:
    """Get all monitoring metrics for a flow across all categories."""
    result = _monitoring.get_all_metrics(flow_arn, hours_back)
    return json.dumps(result, default=str)


@tool
def emx_check_issues(flow_arn: str, hours_back: int = 24) -> str:
    """Cross-category issue scan for a flow with severity classification."""
    result = _monitoring.check_flow_issues(flow_arn, hours_back)
    return json.dumps(result, default=str)


ALL_TOOLS = [
    emx_list_flows,
    emx_describe_flow,
    emx_start_flow,
    emx_stop_flow,
    emx_get_thumbnail,
    emx_get_flow_metrics,
    emx_check_issues,
]
