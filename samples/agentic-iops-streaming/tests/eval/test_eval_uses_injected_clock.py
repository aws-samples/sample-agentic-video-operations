"""Approval evals use their injected clock, independent of wall time."""

import ast
import functools
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from load_eval_scenarios import load_eval_scenarios
from run_eval_scenario import ROOT, EvalClock, run_scenario
from scenario_models import ModelBlock
from scripted_eval_model import ScriptedEvalModel

from agentic_iops_streaming.adapters.signal_maps.discover_signal_map import DiscoveryPolicy
from agentic_iops_streaming.adapters.workflow_store.local_workflow_store import LocalWorkflowStore
from agentic_iops_streaming.bootstrap.create_agentic_iops import create_agentic_iops
from agentic_iops_streaming.bootstrap.create_workflow_tools import (
    WorkflowTools,
    create_workflow_tools,
)
from agentic_iops_streaming.domain.agentic_iops_request import AgenticIopsRequest, ApprovalDecision
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from agentic_iops_streaming.workflows.run_agentic_iops_turn import stream_agentic_iops_turn
from media_ops_contracts.domain_pack import WriteTool

pytestmark = pytest.mark.eval
SCENARIOS = ROOT / "samples/agentic-iops-streaming/tests/scenarios"
PACK_WRITE_PATHS = [
    Path("samples/mediaconnect/src/mediaconnect_mcp/domain_pack.py"),
    Path("samples/mediaconnect/src/mediaconnect_mcp/tool_surface/create_write_tools.py"),
    Path("samples/medialive/src/medialive_mcp/domain_pack.py"),
    Path("samples/medialive/src/medialive_mcp/tool_surface/create_write_tools.py"),
    Path(
        "samples/agentic-iops-streaming/src/agentic_iops_streaming/bootstrap/create_workflow_tools.py"
    ),
    Path("samples/agentic-iops-streaming/src/agentic_iops_streaming/workflows/save_workflow.py"),
]
FLOW = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-contribution:flow-1"
PROPOSAL = {
    "workflow_id": "demo-live-path-ab12cd",
    "version": "1",
    "entry_point_arn": FLOW,
    "name": "demo live path",
    "content_sha256": "c386d5bc1b2be66cab962f703ed8ba1aab3242b2e1adc33ac1350da641aef391",
}


class FarFutureDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2099, 1, 1, tzinfo=tz or UTC)


def test_write_scenario_passes_when_wall_clock_is_far_in_the_future(tmp_path):
    scenario = next(
        item for item in load_eval_scenarios(SCENARIOS) if item.name == "srt_packet_loss"
    )

    with patch("media_ops_contracts.read_utc_now.datetime", FarFutureDateTime):
        result = run_scenario(scenario, tmp_path)

    assert result.passed, result.failures
    assert len(result.verifications) == 1
    assert result.verifications[0].verified


@pytest.mark.parametrize("relative_path", PACK_WRITE_PATHS)
def test_pack_write_paths_do_not_read_the_wall_clock_directly(relative_path):
    tree = ast.parse((ROOT / relative_path).read_text())
    direct_reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "datetime"
    ]

    assert direct_reads == []


def test_workflow_save_passes_when_wall_clock_is_far_in_the_future(tmp_path):
    """The coordinator's write takes the same injected clock as the approval it checks."""
    clock = EvalClock()
    key = b"eval-only-not-a-secret"
    environment = {"DEMO": "1", "DEMO_SCENARIO": "workflow_discovery", "MEMORY_ID": ""}
    with patch.dict(os.environ, environment):
        settings = AgenticIopsSettings(
            approval_signing_key=key.decode(),
            demo=True,
            demo_scenario="workflow_discovery",
            fixtures_dir=ROOT / "fixtures",
            session_dir=tmp_path / "sessions",
        )
        workflow_tools = create_workflow_tools(
            settings,
            LocalWorkflowStore(tmp_path / "workflows"),
            signing_key=key,
            now=clock,
            policy=DiscoveryPolicy(sleep=lambda _: None),
            suffix="ab12cd",
        )
        [write] = workflow_tools.writes
        saves: list[str] = []

        @functools.wraps(write.function)
        def observed_save(**kwargs):  # what the eval runner does to count attempted writes
            saves.append(kwargs["workflow_id"])
            return write.function(**kwargs)

        workflow_tools = WorkflowTools(
            reads=workflow_tools.reads,
            writes=[WriteTool(function=observed_save, resource_parameter=write.resource_parameter)],
        )
        turns = [
            [
                ModelBlock(
                    tool="discover_workflow",
                    input={"entry_point_arn": FLOW, "name": "demo live path"},
                )
            ],
            [ModelBlock(tool="save_workflow", input=PROPOSAL)],
            [ModelBlock(answer="Saved.")],
        ]
        iops = create_agentic_iops(
            settings, packs=[], model=ScriptedEvalModel(turns), workflow_tools=workflow_tools
        )

        def turn(request: AgenticIopsRequest) -> list:
            return list(
                stream_agentic_iops_turn(
                    iops, request, session_id="eval-clock", actor_id="eval-operator", clock=clock
                )
            )

        with patch("media_ops_contracts.read_utc_now.datetime", FarFutureDateTime):
            asked = turn(AgenticIopsRequest(prompt="Discover and save the demo live path."))
            [approval] = [event for event in asked if event.type == "approval_requested"]
            answered = turn(
                AgenticIopsRequest(
                    decision=ApprovalDecision(approval_id=approval.approval_id, approve=True)
                )
            )

    verifications = [event for event in answered if event.type == "verification_completed"]
    assert saves == ["demo-live-path-ab12cd"]
    assert len(verifications) == 1, "the approved save returned no verified ActionResult"
    [verification] = verifications
    assert verification.verified
    assert (verification.before_state, verification.after_state) == ("absent", "v1 c386d5bc1b2b")
