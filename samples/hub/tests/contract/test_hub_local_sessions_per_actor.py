"""Local sessions are kept per actor, as deployed AgentCore Memory keeps them (T54).

Without MEMORY_ID the hub stores sessions as files. They were keyed by session id only, so
two operators who used the same session id shared history and agent.state, and the second
was told the first's pending approval id.
"""

import re
from pathlib import Path

from hub_test_setup import OPERATOR, SESSION, build_hub, only, types
from scripted_model import ScriptedModel, call, say

from media_ops_hub.bootstrap.create_session_manager import create_session_manager
from media_ops_hub.settings.runtime_settings import HubSettings

STOP = call("stop_channel", "use-1", channel_id="ch-1")
OTHER = "operator-b"


def test_another_operator_on_the_same_session_id_sees_none_of_its_history(tmp_path):
    model = ScriptedModel([STOP], [say("ch-1 is RUNNING.")])
    hub = build_hub(tmp_path, model)
    approval = only(hub.ask("Stop ch-1."), "approval_requested")

    events = hub.ask("Is ch-1 healthy?", actor=OTHER)

    assert "error" not in types(events)
    assert approval.approval_id not in repr(events)
    seen = repr(model.messages)
    assert "Is ch-1 healthy?" in seen and "Stop ch-1." not in seen


def test_the_first_operator_still_resumes_its_own_pending_approval(tmp_path):
    hub = build_hub(tmp_path, ScriptedModel([STOP], [say("ok")], [say("Stopped.")]))
    approval = only(hub.ask("Stop ch-1."), "approval_requested")
    hub.ask("Is ch-1 healthy?", actor=OTHER)

    events = hub.decide(approval.approval_id, approve=True)

    assert "error" not in types(events) and len(hub.pack.approvals) == 1
    assert hub.pack.states["ch-1"] == "IDLE"


def test_an_actor_id_cannot_choose_where_its_session_is_stored(tmp_path):
    settings = HubSettings(session_dir=tmp_path)

    for actor in ("../../escape", "/etc", "a/b", "operator-a", "  "):
        manager = create_session_manager(settings, SESSION, actor)
        storage = Path(manager.storage_dir).resolve()

        assert storage.parent == tmp_path.resolve(), actor
        assert re.fullmatch(r"actor_[0-9a-f]{32}", storage.name), actor


def test_each_actor_has_its_own_directory_and_the_same_actor_always_the_same(tmp_path):
    settings = HubSettings(session_dir=tmp_path)

    def storage(actor):
        return create_session_manager(settings, SESSION, actor).storage_dir

    assert storage(OPERATOR) == storage(OPERATOR) != storage(OTHER)
