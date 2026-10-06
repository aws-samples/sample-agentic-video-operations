"""Register MediaConnect adapters as MCP tools and serve stdio."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastmcp import FastMCP

from media_ops_contracts.approved_action import (
    APPROVAL_LIFETIME,
    ActionProposal,
    ApprovedAction,
    sign_approved_action,
)
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.adapters.media_connect.start_flow import start_flow as apply_start_flow
from mediaconnect_mcp.adapters.media_connect.stop_flow import stop_flow as apply_stop_flow
from mediaconnect_mcp.adapters.media_connect.verify_flow_state import FlowActionResult
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import (
    MediaConnectClients,
    create_mediaconnect_clients,
)
from mediaconnect_mcp.entrypoints.report_tool_failures import report_tool_failures
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings, load_runtime_settings
from mediaconnect_mcp.tool_surface.create_read_tools import create_read_tools

READ_ONLY = {"readOnlyHint": True}
START_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
STOP_WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True}


def build_mediaconnect_server(
    settings: RuntimeSettings | None = None,
    clients: MediaConnectClients | None = None,
) -> FastMCP:
    """Build the server and inject one regional client per external system."""
    runtime = settings or load_runtime_settings()
    runtime_clients = clients or create_mediaconnect_clients(runtime)
    signing_key = _read_signing_key(runtime)
    server = FastMCP(
        "MediaConnect MCP Server",
        instructions="Inspect live-video transport and require explicit approval for flow writes.",
    )
    for read_tool in create_read_tools(runtime, runtime_clients):
        server.tool(report_tool_failures(read_tool), annotations=READ_ONLY)
    if runtime.allow_writes:
        _register_write_tools(server, runtime_clients.mediaconnect, signing_key)
    return server


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
    return resolve_approval_signing_key(settings.approval_signing_key.get_secret_value())


def main() -> None:
    settings = load_runtime_settings()
    clients = create_mediaconnect_clients(settings)
    build_mediaconnect_server(settings, clients).run()


if __name__ == "__main__":
    main()
