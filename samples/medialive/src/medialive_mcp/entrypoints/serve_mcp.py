"""MCP stdio server for MediaLive (`just run medialive`).

Read tools are always registered. Write tools exist only with ALLOW_WRITES=true; each one
needs `confirm_resource_id` equal to the channel id, the MCP client's own tool-approval
prompt is the human approval, and the adapter verifies the result (write_safe_tools.md §3).
"""

import functools

from fastmcp import FastMCP

from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from medialive_mcp.bootstrap.create_medialive_clients import (
    MediaLiveClients,
    create_medialive_clients,
)
from medialive_mcp.domain.resolve_channel_id import resolve_channel_id
from medialive_mcp.entrypoints.register_write_tools import register_write_tools
from medialive_mcp.entrypoints.report_tool_failures import report_tool_failures
from medialive_mcp.settings.runtime_settings import RuntimeSettings, load_runtime_settings
from medialive_mcp.tool_surface.create_read_tools import create_read_tools

READ_ONLY = {"readOnlyHint": True}


def build_mcp_server(settings: RuntimeSettings, clients: MediaLiveClients) -> FastMCP:
    mcp = FastMCP("MediaLive")
    for read_tool in create_read_tools(settings, clients):
        mcp.tool(report_tool_failures(read_tool), annotations=READ_ONLY)
    if settings.allow_writes:
        channel = functools.partial(
            resolve_channel_id, default_channel_id=settings.medialive_channel_id
        )
        signing_key = resolve_approval_signing_key(settings.approval_signing_key)
        register_write_tools(mcp, clients, channel, signing_key)
    return mcp


def main() -> None:
    settings = load_runtime_settings()
    build_mcp_server(settings, create_medialive_clients(settings)).run()


if __name__ == "__main__":
    main()
