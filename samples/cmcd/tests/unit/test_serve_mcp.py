import asyncio
from pathlib import Path

from fastmcp import Client

import cmcd_mcp.entrypoints.serve_mcp as serve_mcp
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


def test_average_bitrate_tool_accepts_session_and_content_filters():
    async def call_average_tool():
        async with Client(demo_server()) as client:
            return await client.call_tool(
                "get_average_bitrate",
                {
                    "cmcd_sid": "demo-session-west",
                    "cmcd_cid": "demo-content",
                },
            )

    result = asyncio.run(call_average_tool())

    assert result.structured_content["average_bitrate_kbps"] == 4200
    assert result.structured_content["session_id"] == "demo-session-west"
    assert result.structured_content["content_id"] == "demo-content"


def test_live_settings_do_not_require_an_unused_aws_region():
    settings = RuntimeSettings(
        influxdb_url="https://influxdb.example.com",
        influxdb_token="token",
        influxdb_org="org",
    )

    assert settings.demo is False


def test_runtime_settings_use_the_template_bucket_default_and_accept_the_deployed_output():
    assert RuntimeSettings().influxdb_bucket == "cmcd-metrics"
    assert RuntimeSettings(influxdb_bucket="").influxdb_bucket == "cmcd-metrics"
    assert RuntimeSettings(influxdb_bucket="event-specific-cmcd").influxdb_bucket == (
        "event-specific-cmcd"
    )


def test_live_server_queries_the_bucket_from_runtime_settings(monkeypatch):
    received = []
    monkeypatch.setattr(
        serve_mcp,
        "query_influxdb",
        lambda flux, **_connection: received.append(flux)
        or [{"cmcd_sid": "demo-session", "cmcd_cid": "demo-content"}],
    )
    server = build_cmcd_server(
        RuntimeSettings(
            influxdb_url="https://influxdb.example.com",
            influxdb_token="token",
            influxdb_org="org",
            influxdb_bucket="event-specific-cmcd",
        )
    )

    async def call_tool():
        async with Client(server) as client:
            return await client.call_tool("list_session_and_content_ids")

    result = asyncio.run(call_tool())

    assert result.structured_content["session_ids"] == ["demo-session"]
    assert received
    assert all('from(bucket: "event-specific-cmcd")' in flux for flux in received)


def test_the_live_server_starts_without_influxdb_settings_and_each_tool_says_what_is_missing(
    monkeypatch,
):
    for name in ("INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "DEMO"):
        monkeypatch.delenv(name, raising=False)
    server = build_cmcd_server(RuntimeSettings(influxdb_org="org"))

    async def call_tool():
        async with Client(server) as client:
            return await client.call_tool("list_session_and_content_ids", raise_on_error=False)

    result = asyncio.run(call_tool())

    assert result.is_error
    [content] = result.content
    assert content.text.startswith("InvalidRequest: INFLUXDB_URL, INFLUXDB_TOKEN are not set.")
    assert "just cmcd-token" in content.text
