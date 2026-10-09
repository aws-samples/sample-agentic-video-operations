"""The coordinator's workflow tools on the agent's surface (§8.1).

What matters here is the wiring, not the logic: the four tools are registered under the
coordinator, `save_workflow` reaches the §4 approval hook with `workflow_id` as its resource,
neither the approval nor the session's proposals appear in any schema the model sees, and
ALLOW_WORKFLOW_DISCOVERY off removes all four.
"""

from datetime import UTC, datetime
from pathlib import Path

from test_workflow_discovery import FAST, FIXTURES, FLOW, clock, store

from agentic_iops_streaming.bootstrap.create_workflow_tools import create_workflow_tools
from agentic_iops_streaming.bootstrap.wrap_workflow_tools import wrap_workflow_tools
from agentic_iops_streaming.domain.workflow_proposal_state import (
    read_workflow_proposals,
    write_workflow_proposal,
)
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from agentic_iops_streaming.workflows.discover_workflow import discover_workflow
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient

TOOL_NAMES = {"discover_workflow", "save_workflow", "list_workflows", "get_workflow"}


def settings(**changes) -> AgenticIopsSettings:
    return AgenticIopsSettings(
        agent_model_id="us.anthropic.claude-sonnet-4-6",
        demo=True,
        demo_scenario="workflow_discovery",
        fixtures_dir=FIXTURES,
        **changes,
    )


def tools_of(tmp_path: Path, suffix: str | None = None, **changes):
    return create_workflow_tools(
        settings(**changes),
        store(tmp_path),
        signing_key=b"key",
        medialive=ReplayFixtureClient(
            "medialive", scenario="workflow_discovery", fixtures_dir=FIXTURES
        ),
        policy=FAST,
        suffix=suffix,
    )


def test_the_four_tools_are_registered_with_one_approved_write(tmp_path):
    workflow_tools = tools_of(tmp_path)

    reads = {function.__name__ for function in workflow_tools.reads}
    [write] = workflow_tools.writes
    assert reads == TOOL_NAMES - {"save_workflow"}
    assert write.function.__name__ == "save_workflow"
    assert write.resource_parameter == "workflow_id"  # the §4 hook's resource


def test_no_tool_is_registered_when_workflow_discovery_is_off(tmp_path):
    workflow_tools = tools_of(tmp_path, allow_workflow_discovery=False)

    assert workflow_tools.is_empty
    assert wrap_workflow_tools(workflow_tools) == []


def test_the_setting_is_on_by_default_and_separate_from_allow_writes():
    default = AgenticIopsSettings(agent_model_id="us.anthropic.claude-sonnet-4-6")
    assert default.allow_workflow_discovery is True
    assert default.allow_writes is False


def test_the_model_never_sees_the_approval_or_the_session_proposals(tmp_path):
    wrapped = {tool.tool_name: tool for tool in wrap_workflow_tools(tools_of(tmp_path))}

    assert set(wrapped) == TOOL_NAMES
    properties = wrapped["save_workflow"].tool_spec["inputSchema"]["json"]["properties"]
    assert "approved_action" not in properties and "proposals" not in properties
    assert {"workflow_id", "version", "entry_point_arn", "name", "content_sha256"} <= set(
        properties
    )
    discover = wrapped["discover_workflow"].tool_spec["inputSchema"]["json"]["properties"]
    assert set(discover) == {"entry_point_arn", "name"}


def test_a_write_without_the_hook_s_approval_is_refused_before_the_store(tmp_path):
    wrapped = {tool.tool_name: tool for tool in wrap_workflow_tools(tools_of(tmp_path))}
    answer = run_tool(wrapped["save_workflow"], {"workflow_id": "demo-chain-ab12cd"}, FakeState())

    assert answer["status"] == "error"
    assert "ApprovalRequired" in answer["content"][0]["text"]


def test_a_discovered_proposal_is_kept_in_the_session_for_the_later_save(tmp_path):
    wrapped = {tool.tool_name: tool for tool in wrap_workflow_tools(tools_of(tmp_path))}
    state = FakeState()

    run_tool(wrapped["discover_workflow"], {"entry_point_arn": FLOW, "name": "demo chain"}, state)

    [held] = read_workflow_proposals(state).values()
    assert held.entry_point_arn == FLOW and held.content_sha256


def test_a_pinned_suffix_makes_the_new_workflow_id_predictable(tmp_path):
    """Evals and tests pin it; a deployment leaves it random, as two runs then differ."""
    pinned = {fn.__name__: fn for fn in tools_of(tmp_path, suffix="ab12cd").reads}
    random = {fn.__name__: fn for fn in tools_of(tmp_path / "other").reads}

    proposal = pinned["discover_workflow"](entry_point_arn=FLOW, name="demo chain")
    other = random["discover_workflow"](entry_point_arn=FLOW, name="demo chain")

    assert proposal.workflow_id == "demo-chain-ab12cd"
    assert other.workflow_id.startswith("demo-chain-") and other.workflow_id != proposal.workflow_id


def test_a_rediscovery_replaces_the_proposal_it_held_for_that_workflow(tmp_path):
    state = FakeState()
    first = discover_workflow(
        ReplayFixtureClient("medialive", scenario="workflow_discovery", fixtures_dir=FIXTURES),
        store(tmp_path),
        entry_point_arn=FLOW,
        name="demo chain",
        now=clock,
        policy=FAST,
        suffix="ab12cd",
    )
    write_workflow_proposal(state, first)
    write_workflow_proposal(state, first.model_copy(update={"name": "renamed"}))

    held = read_workflow_proposals(state)
    assert len(held) == 1 and held[first.workflow_id].name == "renamed"


class FakeState:
    """The agent state the tools read and write, as Strands' AgentState behaves."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get(self, key: str) -> object:
        return self.values.get(key)

    def set(self, key: str, value: object) -> None:
        self.values[key] = value


class FakeAgent:
    def __init__(self, state: FakeState) -> None:
        self.state = state


class FakeToolContext:
    def __init__(self, state: FakeState, tool_use: dict) -> None:
        self.agent = FakeAgent(state)
        self.tool_use = tool_use


def run_tool(wrapped, inputs: dict, state: FakeState):
    """Call a wrapped tool the way Strands would, with a tool context."""
    context = FakeToolContext(state, {"name": wrapped.tool_name, "input": inputs})
    return wrapped._tool_func(**inputs, tool_context=context)


def test_the_discovered_proposal_round_trips_through_json_state(tmp_path):
    """Session state is serialized between requests, so the proposal must survive that."""
    state = FakeState()
    proposal = discover_workflow(
        ReplayFixtureClient("medialive", scenario="workflow_discovery", fixtures_dir=FIXTURES),
        store(tmp_path),
        entry_point_arn=FLOW,
        name="demo chain",
        now=clock,
        policy=FAST,
        suffix="ab12cd",
    )
    write_workflow_proposal(state, proposal)

    import json

    reloaded = FakeState()
    reloaded.values = json.loads(json.dumps(state.values))  # what a session store does

    [held] = read_workflow_proposals(reloaded).values()
    assert held == proposal
    assert held.discovered_at == datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
