"""`just demo` runs the real agent and medialive pack on fixtures, with no AWS client at all."""

import os
from pathlib import Path

import boto3
import pytest
from scripted_model import ScriptedModel

from agentic_iops_streaming.bootstrap.wrap_pack_tools import wrap_pack_tools
from agentic_iops_streaming.demo.run_demo import DEMO_ENVIRONMENT, run_demo
from agentic_iops_streaming.demo.scripted_demo_model import DEMO_TURNS
from media_ops_contracts.domain_pack import DomainPackError

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


class RecordingDemoModel(ScriptedModel):
    def __init__(self):
        super().__init__(*DEMO_TURNS)


def refuse_real_client(*args, **kwargs):
    raise AssertionError("the demo created a real boto3 client")


def test_the_demo_investigates_input_loss_from_fixtures_without_aws(monkeypatch, capsys):
    monkeypatch.setattr(boto3, "client", refuse_real_client)
    monkeypatch.setattr(boto3.session.Session, "client", refuse_real_client)
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    for name in DEMO_ENVIRONMENT:  # run_demo sets these in os.environ; restore them afterwards
        monkeypatch.setenv(name, "unset-by-test")
    model = RecordingDemoModel()

    events = run_demo(model=model)

    tools = [event.tool for event in events if event.type == "tool_called"]
    assert tools == ["list_channels", "load_skill", "check_channel_issues", "read_channel_logs"]
    results = [b["toolResult"] for m in model.messages for b in m["content"] if "toolResult" in b]
    assert [result["status"] for result in results] == ["success"] * 4
    assert "InputLossSeconds" in results[2]["content"][0]["text"]
    assert "no SRT packets received" in results[3]["content"][0]["text"]
    assert events[-1].type == "final_answer"
    assert os.environ["DEMO"] == "1" and os.environ["ALLOW_WRITES"] == "false"
    assert "Impact:" in capsys.readouterr().out


class Pack:
    def __init__(self, name, *functions):
        self.name, self.functions = name, functions

    def read_tools(self):
        return list(self.functions)

    def write_tools(self):
        return []


def test_two_packs_offering_the_same_tool_name_stop_startup():
    from pydantic import BaseModel

    class Result(BaseModel):
        ok: bool = True

    def describe_flow() -> Result:
        """Describe."""
        return Result()

    with pytest.raises(DomainPackError, match="describe_flow"):
        wrap_pack_tools(
            [Pack("one", describe_flow), Pack("two", describe_flow)], allow_writes=False
        )  # noqa: E501
