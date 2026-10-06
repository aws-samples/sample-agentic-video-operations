"""The medialive domain pack (extend_the_hub.md §2, §7): entry point, tools, skills and IAM."""

import ast
import asyncio
import dataclasses
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
from medialive_mcp.bootstrap.create_medialive_clients import (
    MediaLiveClients,
    create_medialive_clients,
)
from medialive_mcp.entrypoints.serve_mcp import build_mcp_server
from medialive_mcp.settings.runtime_settings import RuntimeSettings
from medialive_mcp.tool_surface.create_write_tools import create_write_tools

SAMPLE = Path(__file__).resolve().parents[2]
FIXTURES = SAMPLE.parents[1] / "fixtures"
CHANNEL = "1234567"


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))


@pytest.fixture
def pack(demo_env):
    [loaded] = load_domain_packs(["medialive"])
    return loaded


def mcp_read_tool_names() -> set[str]:
    settings = RuntimeSettings(demo=True, fixtures_dir=FIXTURES)
    server = build_mcp_server(settings, create_medialive_clients(settings))

    async def names():
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(names())


def test_the_pack_loads_through_its_entry_point(pack):
    assert isinstance(pack, DomainPack)
    assert pack.name == "medialive"


def test_its_read_tools_are_the_mcp_servers_read_tools(pack):
    assert {tool.__name__ for tool in pack.read_tools()} == mcp_read_tool_names()


def test_its_read_tools_answer_from_fixtures(pack):
    tools = {tool.__name__: tool for tool in pack.read_tools()}
    report = tools["check_channel_issues"](channel_id=CHANNEL, hours_back=1)
    assert any(issue.metric == "InputLossSeconds" for issue in report.issues)


def test_every_write_tool_names_the_channel_and_takes_an_approval(pack):
    writes = pack.write_tools()
    assert len(writes) == 8
    assert {write.resource_parameter for write in writes} == {"channel_id"}


def replay_clients(tmp_path, states):
    scenario = tmp_path / "pack"
    scenario.mkdir()
    channels = [{"Id": CHANNEL, "Name": "demo", "State": state} for state in states]
    (scenario / "medialive.describe_channel.json").write_text(json.dumps({"sequence": channels}))
    (scenario / "medialive.stop_channel.json").write_text("{}")
    medialive = ReplayFixtureClient("medialive", scenario="pack", fixtures_dir=tmp_path)
    unused = {field.name: None for field in dataclasses.fields(MediaLiveClients)}
    return MediaLiveClients(**unused | {"medialive": medialive})


def approval(action, resource_id=CHANNEL, parameters=None):
    proposal = ActionProposal(
        actor_id="operator-1", action=action, resource_id=resource_id, parameters=parameters or {}
    )
    return sign_approved_action(
        proposal,
        approval_id="ap-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        signing_key=resolve_approval_signing_key(""),
    )


def write_tools_by_name(clients):
    tools = create_write_tools(RuntimeSettings(), clients)
    return {tool.function.__name__: tool.function for tool in tools}


def test_an_approval_signed_with_the_shared_process_key_stops_and_verifies(tmp_path):
    clients = replay_clients(tmp_path, ["RUNNING", "IDLE"])
    stop = write_tools_by_name(clients)["stop_channel"]
    result = stop(channel_id=CHANNEL, approved_action=approval("stop_channel"))
    assert (result.before_state, result.after_state, result.verified) == ("RUNNING", "IDLE", True)


def test_an_approval_for_another_channel_never_reaches_aws(tmp_path):
    clients = replay_clients(tmp_path, ["RUNNING"])
    stop = write_tools_by_name(clients)["stop_channel"]
    with pytest.raises(ToolFailure) as failure:
        stop(channel_id=CHANNEL, approved_action=approval("stop_channel", resource_id="7654321"))
    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED
    assert clients.medialive.calls == []


def test_an_approval_for_other_inputs_never_reaches_aws(tmp_path):
    clients = replay_clients(tmp_path, ["RUNNING"])
    switch = write_tools_by_name(clients)["switch_channel_input"]
    approved = approval(
        "switch_channel_input",
        parameters={"action_name": "to-backup", "input_attachment": "demo-backup-srt"},
    )
    with pytest.raises(ToolFailure):
        switch(
            channel_id=CHANNEL,
            action_name="to-backup",
            input_attachment="demo-primary-srt",
            approved_action=approved,
        )
    assert clients.medialive.calls == []


def test_its_skills_parse_and_are_listed_by_name_and_description(pack):
    catalogue = SkillCatalogue.from_paths(pack.skill_paths)
    assert catalogue.names() == ["diagnose-input-loss", "read-channel-health"]
    assert all(line.startswith("- ") for line in catalogue.prompt_lines())


def test_its_fixture_scenarios_exist_with_medialive_responses(pack):
    for scenario in pack.fixture_scenarios:
        assert list((FIXTURES / scenario).glob("medialive.*.json")), scenario


SERVICE_BY_CLIENT = {"medialive": "medialive", "cloudwatch": "cloudwatch", "logs": "logs",
                     "bedrock": "bedrock", "sts": "sts"}  # fmt: skip
IAM_ACTION_OVERRIDES = {"bedrock:Converse": "bedrock:InvokeModel"}
NEEDS_NO_PERMISSION = {"sts:GetCallerIdentity"}  # allowed for every principal


def adapter_operations() -> set[str]:
    """Every AWS operation the adapters call, as an IAM action name."""
    actions = set()
    for path in (SAMPLE / "src/medialive_mcp/adapters").rglob("*.py"):
        tree = ast.parse(path.read_text())
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in ("call_aws_operation", "collect_pages"):
                continue
            client, operation = node.args[0], node.args[1]
            name = client.attr if isinstance(client, ast.Attribute) else client.id
            operation_name = (
                constants[operation.id] if isinstance(operation, ast.Name) else operation.value
            )
            camel = "".join(part.capitalize() for part in operation_name.split("_"))
            action = f"{SERVICE_BY_CLIENT[name]}:{camel}"
            actions.add(IAM_ACTION_OVERRIDES.get(action, action))
    return actions - NEEDS_NO_PERMISSION


def test_iam_permissions_cover_every_aws_operation_the_adapters_call():
    permissions = json.loads((SAMPLE / "iam_permissions.json").read_text())
    granted = {
        action
        for group in ("read", "write")
        for statement in permissions[group]
        for action in statement["actions"]
    }
    operations = adapter_operations()
    assert {"medialive:StopChannel", "cloudwatch:GetMetricData"} <= operations
    assert operations <= granted, operations - granted


def test_write_permissions_are_only_the_write_operations():
    permissions = json.loads((SAMPLE / "iam_permissions.json").read_text())
    writes = {action for statement in permissions["write"] for action in statement["actions"]}
    assert writes == {
        "medialive:StartChannel",
        "medialive:StopChannel",
        "medialive:BatchUpdateSchedule",
    }


def test_log_permissions_name_the_group_medialive_writes_to():
    permissions = json.loads((SAMPLE / "iam_permissions.json").read_text())
    [logs] = [s for s in permissions["read"] if s["actions"][0].startswith("logs:")]
    assert logs["actions"] == ["logs:DescribeLogStreams", "logs:FilterLogEvents"]
    assert logs["resources"] == ["arn:aws:logs:{region}:{account}:log-group:ElementalMediaLive:*"]
