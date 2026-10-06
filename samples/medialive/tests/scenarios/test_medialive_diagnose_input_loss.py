"""Replay fixtures/input_loss end to end: pipeline 0 lost its SRT input, pipeline 1 is fine."""

import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from medialive_mcp.adapters.cloudwatch_logs.read_channel_logs import read_channel_logs
from medialive_mcp.adapters.media_live.describe_channel import describe_channel
from medialive_mcp.adapters.media_live.list_channels import list_channels
from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.entrypoints.serve_mcp import build_mcp_server
from medialive_mcp.settings.runtime_settings import RuntimeSettings
from medialive_mcp.workflows.check_channel_health import (
    check_channel_issues,
    recent_window,
    summarize_channel_metrics,
)

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
CHANNEL = "1234567"


@pytest.fixture
def settings():
    return RuntimeSettings(demo=True, demo_scenario="input_loss", fixtures_dir=FIXTURES)


@pytest.fixture
def clients(settings):
    return create_medialive_clients(settings)


def test_the_channel_is_running_on_its_primary_srt_input(clients):
    [channel] = list_channels(clients.medialive)
    assert (channel.channel_id, channel.state) == (CHANNEL, "RUNNING")
    details = describe_channel(clients.medialive, CHANNEL)
    assert [p.active_input_attachment for p in details.pipelines] == ["demo-primary-srt"] * 2


def test_input_loss_shows_on_pipeline_0_only(clients):
    series = summarize_channel_metrics(clients, CHANNEL, hours_back=1, category="input_health")
    loss = {s.pipeline: sum(s.values) for s in series if s.metric == "InputLossSeconds"}
    assert loss["0"] > 0
    assert loss["1"] == 0


def test_issue_report_names_input_loss_on_pipeline_0(clients):
    report = check_channel_issues(clients, CHANNEL, hours_back=1)
    flagged = {(issue.category, issue.metric, issue.pipeline) for issue in report.issues}
    assert ("input_health", "InputLossSeconds", "0") in flagged
    assert ("channel_health", "ActiveAlerts", "0") in flagged
    assert not any(issue.pipeline == "1" for issue in report.issues)
    assert report.categories["input_health"].score == 70
    # Pipeline 0 is still on slate and alerting: the channel is degraded, not "good".
    assert report.status == "DEGRADED"
    assert report.overall_score == min(
        h.score for h in report.categories.values() if h.score is not None
    )
    assert severities_of(report)[("InputLossSeconds", "0")] == "HIGH"
    keys = [(issue.metric, issue.pipeline) for issue in report.issues]
    assert len(keys) == len(set(keys))


def severities_of(report):
    return {(issue.metric, issue.pipeline): issue.severity for issue in report.issues}


def test_logs_carry_the_srt_evidence(clients):
    result = read_channel_logs(clients, CHANNEL, recent_window(1), "us-west-2")
    assert "no SRT packets" in result.events[0].message
    assert result.events == sorted(result.events, key=lambda event: event.timestamp)


def call_tool(settings, name, arguments):
    server = build_mcp_server(settings, create_medialive_clients(settings))

    async def call():
        async with Client(server) as client:
            names = {tool.name for tool in await client.list_tools()}
            result = await client.call_tool(name, arguments, raise_on_error=False)
            return names, result

    return asyncio.run(call())


def test_mcp_server_diagnoses_without_any_write_tool_by_default(settings):
    names, result = call_tool(settings, "check_channel_issues", {"channel_id": CHANNEL})
    assert not names & {"start_channel", "stop_channel", "switch_channel_input"}
    report = json.loads(result.content[0].text)
    assert any(issue["metric"] == "InputLossSeconds" for issue in report["issues"])


def test_allow_writes_adds_eight_destructive_tools(settings):
    writable = settings.model_copy(update={"allow_writes": True})
    server = build_mcp_server(writable, create_medialive_clients(writable))

    async def list_tools():
        async with Client(server) as client:
            return await client.list_tools()

    tools = asyncio.run(list_tools())
    destructive = {t.name for t in tools if t.annotations and t.annotations.destructiveHint}
    read_only = {t.name for t in tools if t.annotations and t.annotations.readOnlyHint}
    assert len(destructive) == 8 and len(read_only) == 9
    assert "analyze_channel_visual_quality" in read_only
    assert {"stop_channel", "switch_channel_input", "delete_schedule_action"} <= destructive


def test_demo_starts_without_model_ids_and_thumbnail_asks_for_one(monkeypatch):
    for name in ("AGENT_MODEL_ID", "THUMBNAIL_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    settings = RuntimeSettings(demo=True, demo_scenario="input_loss", fixtures_dir=FIXTURES)
    names, result = call_tool(settings, "describe_channel_thumbnail", {"channel_id": CHANNEL})
    assert "list_channels" in names
    assert result.is_error
    assert "THUMBNAIL_MODEL_ID is not set" in result.content[0].text
