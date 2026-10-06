"""The real medialive pack loads through its entry point and answers from fixtures."""

from pathlib import Path

from hub_test_setup import only, types
from scripted_model import ScriptedModel, call, last_tool_result, say

from media_ops_hub.bootstrap.create_hub import create_hub
from media_ops_hub.domain.hub_request import HubRequest
from media_ops_hub.settings.runtime_settings import HubSettings
from media_ops_hub.workflows.run_hub_turn import stream_hub_turn

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


def test_the_hub_reads_a_medialive_channel_in_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    model = ScriptedModel([call("list_channels", "use-1")], [say("One channel has input loss.")])
    hub = create_hub(HubSettings(media_domains="medialive", session_dir=tmp_path), model=model)

    request = HubRequest(prompt="Any problems?")
    events = list(stream_hub_turn(hub, request, session_id="demo", actor_id="operator-a"))

    assert types(events) == ["task_started", "tool_called", "final_answer", "usage_reported"]
    assert only(events, "task_started").specialist == "medialive"
    assert "load_skill" in model.tool_names
    assert not any(name.startswith(("stop_", "start_")) for name in model.tool_names)
    result = last_tool_result(model)
    assert result["status"] == "success"
    assert "demo-channel" in result["content"][0]["text"]
