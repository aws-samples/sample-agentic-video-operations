import asyncio
from pathlib import Path

from fastmcp import Client

from cmcd_mcp.entrypoints.serve_mcp import build_cmcd_server
from cmcd_mcp.settings.runtime_settings import RuntimeSettings

FIXTURES_DIR = Path(__file__).parents[4] / "fixtures"
EXPECTED_TOOLS = {
    "get_average_bitrate",
    "get_session_details",
    "analyze_buffer_events",
    "identify_playback_errors",
    "list_session_and_content_ids",
}


def demo_server():
    return build_cmcd_server(
        RuntimeSettings(
            demo=True,
            demo_scenario="cmcd_rebuffering",
            fixtures_dir=FIXTURES_DIR,
        )
    )


def test_every_registered_tool_is_read_only():
    tools = asyncio.run(demo_server().list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.annotations and tool.annotations.readOnlyHint for tool in tools)


def test_demo_server_answers_from_root_fixtures():
    async def call_buffer_tool():
        async with Client(demo_server()) as client:
            return await client.call_tool("analyze_buffer_events")

    result = asyncio.run(call_buffer_tool())
    assert result.structured_content["low_buffer_count"] == 3
    assert result.structured_content["low_buffer_events"][0]["cdn"] == "demo-cdn"


def test_live_settings_do_not_require_an_unused_aws_region():
    settings = RuntimeSettings(
        influxdb_url="https://influxdb.example.com",
        influxdb_token="token",
        influxdb_org="org",
    )

    assert settings.demo is False
