import asyncio

from fastmcp import Client
from mediaconnect_mcp.entrypoints.serve_mcp import build_mediaconnect_server
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings

READ_TOOLS = {
    "list_flows",
    "describe_flow",
    "describe_flow_source_metadata",
    "describe_flow_thumbnail",
    "get_flow_health_metrics",
    "get_source_health_metrics",
    "get_output_health_metrics",
    "get_media_health_metrics",
    "get_content_quality_metrics",
    "get_all_metrics",
    "check_flow_issues",
    "get_metrics_table",
}
WRITE_TOOLS = {"start_flow", "stop_flow"}
RUNTIME_ENVIRONMENT_NAMES = {
    "AWS_REGION",
    "THUMBNAIL_MODEL_ID",
    "MEDIACONNECT_FLOW_ARN",
    "ALLOW_WRITES",
    "DEMO_SCENARIO",
    "FIXTURES_DIR",
    "APPROVAL_SIGNING_KEY",
}


def settings(tmp_path, *, allow_writes=False):
    return RuntimeSettings(
        aws_region="us-west-2",
        thumbnail_model_id="demo-thumbnail-model",
        allow_writes=allow_writes,
        demo=True,
        demo_scenario="entrypoint",
        fixtures_dir=tmp_path,
        approval_signing_key="test-signing-key",
    )


def test_default_server_registers_only_read_tools(tmp_path):
    tools = asyncio.run(build_mediaconnect_server(settings(tmp_path)).list_tools())

    assert {tool.name for tool in tools} == READ_TOOLS
    assert all(tool.annotations and tool.annotations.readOnlyHint for tool in tools)


def test_demo_server_starts_without_an_env_file(monkeypatch):
    for name in RUNTIME_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO", "1")

    runtime = RuntimeSettings()
    tools = asyncio.run(build_mediaconnect_server(runtime).list_tools())

    assert runtime.aws_region is None
    assert runtime.thumbnail_model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert {tool.name for tool in tools} == READ_TOOLS


def test_write_tools_require_explicit_enablement_and_declare_annotations(tmp_path):
    tools = asyncio.run(
        build_mediaconnect_server(settings(tmp_path, allow_writes=True)).list_tools()
    )
    tools_by_name = {tool.name: tool for tool in tools}

    assert set(tools_by_name) == READ_TOOLS | WRITE_TOOLS
    assert tools_by_name["start_flow"].annotations.idempotentHint is True
    assert tools_by_name["start_flow"].annotations.destructiveHint is False
    assert tools_by_name["stop_flow"].annotations.idempotentHint is True
    assert tools_by_name["stop_flow"].annotations.destructiveHint is True


def test_stop_flow_rejects_a_different_confirmation_resource(tmp_path):
    async def call_stop():
        server = build_mediaconnect_server(settings(tmp_path, allow_writes=True))
        async with Client(server) as client:
            return await client.call_tool(
                "stop_flow",
                {
                    "flow_arn": "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo:flow-1",
                    "confirm_resource_id": (
                        "arn:aws:mediaconnect:us-west-2:111122223333:flow:other:flow-2"
                    ),
                },
                raise_on_error=False,
            )

    result = asyncio.run(call_stop())

    assert result.is_error is True
    assert "confirm_resource_id must exactly match flow_arn" in result.content[0].text
    assert "Approve the MCP tool and enter the exact flow ARN again" in result.content[0].text
