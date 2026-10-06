"""Register MediaConnect adapters as MCP tools and serve stdio."""

import secrets
from datetime import UTC, datetime
from functools import partial
from typing import Any, cast
from uuid import uuid4

from fastmcp import FastMCP

from media_ops_contracts.approved_action import (
    APPROVAL_LIFETIME,
    ActionProposal,
    ApprovedAction,
    sign_approved_action,
)
from media_ops_contracts.create_aws_client import create_aws_client
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    FlowMetrics,
    MetricCategory,
    read_flow_metrics,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    FlowDetails,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    describe_flow as read_flow,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow_source_metadata import (
    FlowSourceMetadata,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow_source_metadata import (
    describe_flow_source_metadata as read_source_metadata,
)
from mediaconnect_mcp.adapters.media_connect.list_flows import (
    FlowList,
)
from mediaconnect_mcp.adapters.media_connect.list_flows import (
    list_flows as read_flows,
)
from mediaconnect_mcp.adapters.media_connect.start_flow import start_flow as apply_start_flow
from mediaconnect_mcp.adapters.media_connect.stop_flow import stop_flow as apply_stop_flow
from mediaconnect_mcp.adapters.media_connect.verify_flow_state import FlowActionResult
from mediaconnect_mcp.entrypoints.report_tool_failures import report_tool_failures
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings
from mediaconnect_mcp.workflows.build_metrics_table import MetricsTable, build_metrics_table
from mediaconnect_mcp.workflows.describe_flow_thumbnail import (
    FlowThumbnailDescription,
)
from mediaconnect_mcp.workflows.describe_flow_thumbnail import (
    describe_flow_thumbnail as read_thumbnail_description,
)
from mediaconnect_mcp.workflows.identify_flow_issues import (
    FlowIssueReport,
    identify_flow_issues,
)
from mediaconnect_mcp.workflows.inspect_all_flow_metrics import (
    AllFlowMetrics,
    inspect_all_flow_metrics,
)

READ_ONLY = {"readOnlyHint": True}
START_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
STOP_WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True}


def build_mediaconnect_server(settings: RuntimeSettings | None = None) -> FastMCP:
    """Build the server and inject one regional client per external system."""
    runtime = settings or RuntimeSettings()
    clients = {
        service: create_aws_client(
            service,
            region=cast(str, runtime.aws_region),
            demo=runtime.demo,
            demo_scenario=runtime.demo_scenario,
            fixtures_dir=runtime.fixtures_dir,
        )
        for service in ("mediaconnect", "cloudwatch", "bedrock-runtime")
    }
    signing_key = _read_signing_key(runtime)
    server = FastMCP(
        "MediaConnect MCP Server",
        instructions="Inspect live-video transport and require explicit approval for flow writes.",
    )

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def list_flows() -> FlowList:
        """List MediaConnect flows in the configured AWS region."""
        return read_flows(clients["mediaconnect"])

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def describe_flow(flow_arn: str) -> FlowDetails:
        """Describe one flow's state, source, outputs, and AWS errors."""
        return read_flow(clients["mediaconnect"], flow_arn)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def describe_flow_source_metadata(flow_arn: str) -> FlowSourceMetadata:
        """Read transport-stream and NDI metadata for one flow source."""
        return read_source_metadata(clients["mediaconnect"], flow_arn)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def describe_flow_thumbnail(flow_arn: str) -> FlowThumbnailDescription:
        """Describe the current source thumbnail with the configured vision model."""
        return read_thumbnail_description(
            clients["mediaconnect"],
            clients["bedrock-runtime"],
            flow_arn,
            cast(str, runtime.thumbnail_model_id),
        )

    _register_metric_tools(server, clients["cloudwatch"])
    if runtime.allow_writes:
        _register_write_tools(server, clients["mediaconnect"], signing_key)
    return server


def _register_metric_tools(server: FastMCP, cloudwatch: Any) -> None:
    def read(category: MetricCategory, flow_arn: str, hours_back: int) -> FlowMetrics:
        return read_flow_metrics(cloudwatch, flow_arn, category, hours_back, datetime.now(UTC))

    def read_all(flow_arn: str, hours_back: int) -> AllFlowMetrics:
        return inspect_all_flow_metrics(
            flow_arn,
            partial(read, flow_arn=flow_arn, hours_back=hours_back),
        )

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_flow_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read flow-level transport and TR 101 290 metrics."""
        return read(MetricCategory.FLOW_HEALTH, flow_arn, hours_back)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_source_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read source connection, loss, recovery, and merge metrics."""
        return read(MetricCategory.SOURCE_HEALTH, flow_arn, hours_back)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_output_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read output connection, packet, and payload metrics."""
        return read(MetricCategory.OUTPUT_HEALTH, flow_arn, hours_back)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_media_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read source jitter, latency, uptime, and consecutive-drop metrics."""
        return read(MetricCategory.MEDIA_HEALTH, flow_arn, hours_back)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_content_quality_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read missing-stream, black-frame, frozen-frame, and silence metrics."""
        return read(MetricCategory.CONTENT_QUALITY, flow_arn, hours_back)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_all_metrics(flow_arn: str, hours_back: int = 1) -> AllFlowMetrics:
        """Read all five MediaConnect metric categories."""
        return read_all(flow_arn, hours_back)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def check_flow_issues(flow_arn: str, hours_back: int = 24) -> FlowIssueReport:
        """Identify non-zero loss, drop, disconnect, error, and missing-stream signals."""
        return identify_flow_issues(read_all(flow_arn, hours_back))

    @server.tool(annotations=READ_ONLY)
    @report_tool_failures
    def get_metrics_table(flow_arn: str, hours_back: int = 6) -> MetricsTable:
        """Flatten all metric points into chronological rows for charting."""
        return build_metrics_table(read_all(flow_arn, hours_back))


def _register_write_tools(server: FastMCP, media_connect: Any, signing_key: bytes) -> None:
    @server.tool(annotations=START_WRITE)
    @report_tool_failures
    def start_flow(flow_arn: str, confirm_resource_id: str) -> FlowActionResult:
        """Start the exact flow named again in confirm_resource_id."""
        approved = _approve_stdio_action("start_flow", flow_arn, confirm_resource_id, signing_key)
        return apply_start_flow(approved, media_connect, signing_key, datetime.now(UTC))

    @server.tool(annotations=STOP_WRITE)
    @report_tool_failures
    def stop_flow(flow_arn: str, confirm_resource_id: str) -> FlowActionResult:
        """Stop the exact flow named again in confirm_resource_id."""
        approved = _approve_stdio_action("stop_flow", flow_arn, confirm_resource_id, signing_key)
        return apply_stop_flow(approved, media_connect, signing_key, datetime.now(UTC))


def _approve_stdio_action(
    action: str,
    resource_id: str,
    confirm_resource_id: str,
    signing_key: bytes,
) -> ApprovedAction:
    if confirm_resource_id != resource_id:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "confirm_resource_id must exactly match flow_arn.",
            "Approve the MCP tool and enter the exact flow ARN again.",
        )
    now = datetime.now(UTC)
    proposal = ActionProposal(
        actor_id="mcp-stdio-operator",
        action=action,
        resource_id=resource_id,
    )
    return sign_approved_action(
        proposal,
        approval_id=str(uuid4()),
        expires_at=now + APPROVAL_LIFETIME,
        signing_key=signing_key,
    )


def _read_signing_key(settings: RuntimeSettings) -> bytes:
    configured = settings.approval_signing_key.get_secret_value()
    return configured.encode() if configured else secrets.token_bytes(32)


def main() -> None:
    build_mediaconnect_server().run()


if __name__ == "__main__":
    main()
