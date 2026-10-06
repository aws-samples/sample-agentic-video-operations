"""The MediaConnect domain pack: entry point, shared reads, safe writes, skills and IAM."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastmcp import Client

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.domain_pack import DomainPack, load_domain_packs
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.skill_catalogue import SkillCatalogue
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import (
    MediaConnectClients,
    create_mediaconnect_clients,
)
from mediaconnect_mcp.entrypoints.serve_mcp import build_mediaconnect_server
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings
from mediaconnect_mcp.tool_surface.create_write_tools import create_write_tools

SAMPLE = Path(__file__).resolve().parents[2]
FIXTURES = SAMPLE.parents[1] / "fixtures"
FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-flow:flow-1"
SRT_FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-contribution:flow-1"


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))


@pytest.fixture
def pack(demo_env):
    [loaded] = load_domain_packs(["mediaconnect"])
    return loaded


def demo_settings() -> RuntimeSettings:
    return RuntimeSettings(
        demo=True,
        demo_scenario="srt_packet_loss",
        fixtures_dir=FIXTURES,
    )


def mcp_read_tool_names() -> set[str]:
    settings = demo_settings()
    server = build_mediaconnect_server(settings, create_mediaconnect_clients(settings))

    async def names():
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(names())


def test_the_pack_loads_through_its_entry_point(pack):
    assert isinstance(pack, DomainPack)
    assert pack.name == "mediaconnect"


def test_its_read_tools_are_the_mcp_servers_read_tools(pack):
    assert {tool.__name__ for tool in pack.read_tools()} == mcp_read_tool_names()


def test_its_read_tools_answer_from_fixtures(pack):
    tools = {tool.__name__: tool for tool in pack.read_tools()}
    flows = tools["list_flows"]()
    issues = tools["check_flow_issues"](FLOW_ARN, hours_back=1)

    assert flows.count == 1
    assert issues.issue_count > 0


def test_every_write_tool_names_the_flow_and_takes_an_approval(pack):
    writes = pack.write_tools()
    assert {write.function.__name__ for write in writes} == {"start_flow", "stop_flow"}
    assert {write.resource_parameter for write in writes} == {"flow_arn"}


def replay_clients(tmp_path: Path, action: str, states: list[str]) -> MediaConnectClients:
    scenario = tmp_path / "pack"
    scenario.mkdir()
    responses = {
        "sequence": [
            {"Flow": {"FlowArn": FLOW_ARN, "Name": "demo-flow", "Status": state}}
            for state in states
        ]
    }
    (scenario / "mediaconnect.describe_flow.json").write_text(json.dumps(responses))
    (scenario / f"mediaconnect.{action}_flow.json").write_text("{}")
    media_connect = ReplayFixtureClient(
        "mediaconnect",
        scenario=scenario.name,
        fixtures_dir=tmp_path,
    )
    return MediaConnectClients(mediaconnect=media_connect, cloudwatch=None, bedrock=None)


def approval(
    action: str,
    *,
    resource_id: str = FLOW_ARN,
    parameters: dict[str, str] | None = None,
):
    proposal = ActionProposal(
        actor_id="operator-1",
        action=action,
        resource_id=resource_id,
        parameters=parameters or {},
    )
    return sign_approved_action(
        proposal,
        approval_id="approval-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        signing_key=resolve_approval_signing_key(""),
    )


def write_tools_by_name(clients: MediaConnectClients):
    tools = create_write_tools(demo_settings(), clients)
    return {tool.function.__name__: tool.function for tool in tools}


@pytest.mark.parametrize(
    ("action", "before", "after"),
    [
        ("start", "STANDBY", "ACTIVE"),
        ("stop", "ACTIVE", "STANDBY"),
    ],
)
def test_an_approval_signed_with_the_shared_process_key_acts_and_verifies(
    tmp_path, action, before, after
):
    clients = replay_clients(tmp_path, action, [before, after])
    write = write_tools_by_name(clients)[f"{action}_flow"]

    result = write(flow_arn=FLOW_ARN, approved_action=approval(f"{action}_flow"))

    assert (result.before_state, result.after_state, result.verified) == (before, after, True)


def test_srt_fixture_replays_an_approved_stop_and_restart():
    settings = demo_settings()
    clients = create_mediaconnect_clients(settings)
    writes = write_tools_by_name(clients)

    initial = clients.mediaconnect.describe_flow(FlowArn=SRT_FLOW_ARN)
    stopped = writes["stop_flow"](
        flow_arn=SRT_FLOW_ARN,
        approved_action=approval("stop_flow", resource_id=SRT_FLOW_ARN),
    )
    restarted = writes["start_flow"](
        flow_arn=SRT_FLOW_ARN,
        approved_action=approval("start_flow", resource_id=SRT_FLOW_ARN),
    )

    assert initial["Flow"]["Status"] == "ACTIVE"
    assert (stopped.before_state, stopped.after_state, stopped.verified) == (
        "ACTIVE",
        "STANDBY",
        True,
    )
    assert (restarted.before_state, restarted.after_state, restarted.verified) == (
        "STANDBY",
        "ACTIVE",
        True,
    )
    assert [operation for operation, _ in clients.mediaconnect.calls] == [
        "describe_flow",
        "describe_flow",
        "stop_flow",
        "describe_flow",
        "describe_flow",
        "start_flow",
        "describe_flow",
    ]


@pytest.mark.parametrize(
    "approved",
    [
        approval("start_flow"),
        approval("stop_flow", resource_id="arn:aws:mediaconnect:us-west-2:1:flow:other:id"),
        approval("stop_flow", parameters={"unexpected": "value"}),
    ],
)
def test_a_mismatched_approval_never_reaches_aws(tmp_path, approved):
    clients = replay_clients(tmp_path, "stop", ["ACTIVE"])
    stop = write_tools_by_name(clients)["stop_flow"]

    with pytest.raises(ToolFailure) as failure:
        stop(flow_arn=FLOW_ARN, approved_action=approved)

    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED
    assert clients.mediaconnect.calls == []


def test_its_skills_parse_and_are_listed_by_name_and_description(pack):
    catalogue = SkillCatalogue.from_paths(pack.skill_paths)
    assert catalogue.names() == ["diagnose-transport-loss", "inspect-flow-thumbnail"]
    assert all(line.startswith("- ") for line in catalogue.prompt_lines())


def test_its_fixture_scenarios_exist_with_mediaconnect_responses(pack):
    for scenario in pack.fixture_scenarios:
        assert list((FIXTURES / scenario).glob("mediaconnect.*.json")), scenario
