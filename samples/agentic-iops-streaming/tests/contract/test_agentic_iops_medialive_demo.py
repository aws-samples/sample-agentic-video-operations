"""The real medialive pack loads through its entry point and answers from fixtures."""

from pathlib import Path

from agentic_iops_test_setup import only, types
from scripted_model import ScriptedModel, call, last_tool_result, say

from agentic_iops_streaming.bootstrap.create_agentic_iops import create_agentic_iops
from agentic_iops_streaming.domain.agentic_iops_request import AgenticIopsRequest
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from agentic_iops_streaming.workflows.run_agentic_iops_turn import stream_agentic_iops_turn

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


def test_the_agentic_iops_reads_a_medialive_channel_in_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    model = ScriptedModel([call("list_channels", "use-1")], [say("One channel has input loss.")])
    iops = create_agentic_iops(
        AgenticIopsSettings(media_domains="medialive", session_dir=tmp_path), model=model
    )

    request = AgenticIopsRequest(prompt="Any problems?")
    events = list(stream_agentic_iops_turn(iops, request, session_id="demo", actor_id="operator-a"))

    assert types(events) == ["task_started", "tool_called", "final_answer"]
    assert only(events, "task_started").specialist == "medialive"
    assert "load_skill" in model.tool_names
    assert not any(name.startswith(("stop_", "start_")) for name in model.tool_names)
    result = last_tool_result(model)
    assert result["status"] == "success"
    assert "demo-channel" in result["content"][0]["text"]
