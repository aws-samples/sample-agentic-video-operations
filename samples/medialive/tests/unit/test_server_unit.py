"""T15-T16: FastMCP server registration — verify tool count and names."""
import asyncio
import pytest
from unittest.mock import patch


EXPECTED_TOOLS = {
    # Migrated channel tools (14)
    "mcp_list_channels",
    "mcp_describe_channel",
    "mcp_start_channel",
    "mcp_stop_channel",
    "mcp_get_channel_metrics",
    "mcp_get_channel_logs",
    "mcp_describe_channel_thumbnail",
    "mcp_describe_schedule",
    "mcp_create_input_switch_action",
    "mcp_create_scte35_action",
    "mcp_create_pause_action",
    "mcp_create_unpause_action",
    "mcp_delete_schedule_action",
    "mcp_create_immediate_input_switch",
    # Monitoring tools (8)
    "mcp_get_all_metrics",
    "mcp_get_channel_health_metrics",
    "mcp_get_input_health_metrics",
    "mcp_get_output_health_metrics",
    "mcp_get_media_health_metrics",
    "mcp_get_content_quality_metrics",
    "mcp_check_channel_issues",
    "mcp_get_metrics_table",
}


def _get_registered_tool_names():
    """Import server and extract registered tool names from FastMCP."""
    with patch("boto3.client"):
        import server
    mcp = server.mcp
    # FastMCP v2 stores tools via _local_provider._list_tools() (async)
    tools = asyncio.run(mcp._local_provider._list_tools())
    return {t.name for t in tools}


# ── T15 — server.py registers exactly 22 tools ──────────────────────────

class TestT15ToolCount:
    def test_exactly_22_tools(self):
        names = _get_registered_tool_names()
        assert len(names) == 22, f"Expected 22 tools, got {len(names)}: {names}"


# ── T16 — All 22 expected tool names are registered ─────────────────────

class TestT16ToolNames:
    def test_all_expected_names_present(self):
        names = _get_registered_tool_names()
        missing = EXPECTED_TOOLS - names
        assert not missing, f"Missing tools: {missing}"

    def test_no_unexpected_tools(self):
        names = _get_registered_tool_names()
        extra = names - EXPECTED_TOOLS
        assert not extra, f"Unexpected tools: {extra}"
