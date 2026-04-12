"""T13-T14: Server registration tests — verify FastMCP tool registration."""
import sys
import os
import asyncio
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from server import mcp


def _list_tools_sync():
    """Helper to call async list_tools from sync context."""
    return asyncio.run(mcp.list_tools())


# --- T13: server.py registers exactly 22 tools ---

class TestT13ToolCount:
    def test_exactly_22_tools(self):
        tools = _list_tools_sync()
        assert len(tools) == 22, f"Expected 22 tools, got {len(tools)}: {[t.name for t in tools]}"


# --- T14: All expected tool names are registered ---

class TestT14ToolNames:
    EXPECTED_MIGRATED = {
        'mcp_list_channels', 'mcp_describe_channel', 'mcp_start_channel',
        'mcp_stop_channel', 'mcp_get_channel_metrics', 'mcp_get_channel_logs',
        'mcp_describe_channel_thumbnail', 'mcp_describe_schedule',
        'mcp_create_input_switch_action', 'mcp_create_scte35_action',
        'mcp_create_pause_action', 'mcp_create_unpause_action',
        'mcp_delete_schedule_action', 'mcp_create_immediate_input_switch',
    }

    EXPECTED_MONITORING = {
        'mcp_get_all_metrics', 'mcp_get_channel_health_metrics',
        'mcp_get_input_health_metrics', 'mcp_get_output_health_metrics',
        'mcp_get_media_health_metrics', 'mcp_get_content_quality_metrics',
        'mcp_check_channel_issues', 'mcp_get_metrics_table',
    }

    def test_all_migrated_tools_registered(self):
        tools = _list_tools_sync()
        names = {t.name for t in tools}
        missing = self.EXPECTED_MIGRATED - names
        assert not missing, f"Missing migrated tools: {missing}"

    def test_all_monitoring_tools_registered(self):
        tools = _list_tools_sync()
        names = {t.name for t in tools}
        missing = self.EXPECTED_MONITORING - names
        assert not missing, f"Missing monitoring tools: {missing}"

    def test_no_unexpected_tools(self):
        tools = _list_tools_sync()
        names = {t.name for t in tools}
        expected_all = self.EXPECTED_MIGRATED | self.EXPECTED_MONITORING
        unexpected = names - expected_all
        assert not unexpected, f"Unexpected tools registered: {unexpected}"
