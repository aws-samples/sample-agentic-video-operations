"""The AgentCore entrypoint and settings fail safely (extend_the_hub.md §1)."""

import json
from types import SimpleNamespace

import pytest
from hub_test_setup import build_hub
from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER
from pydantic import ValidationError
from scripted_model import ScriptedModel, call, say

from media_ops_hub.entrypoints import handle_agentcore_invocation as entrypoint
from media_ops_hub.settings.runtime_settings import HubSettings

ACTOR = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"


def invoke(payload, *, session="session-a", headers=None):
    context = SimpleNamespace(session_id=session, request_headers=headers or {})
    return [STREAM_EVENT_ADAPTER.validate_python(item) for item in entrypoint.invoke(payload, context)]


def test_a_prompt_streams_the_final_answer_for_the_header_actor(tmp_path, monkeypatch):
    hub = build_hub(tmp_path, ScriptedModel([say("All channels are healthy.")]))
    monkeypatch.setattr(entrypoint, "get_hub", lambda: hub.hub)

    [answer] = invoke({"prompt": "Status?"}, headers={ACTOR: "operator-a"})

    assert answer.type == "final_answer"
    assert answer.session_id == "session-a"


@pytest.mark.parametrize("payload", [{}, {"prompt": "x", "decision": {"approval_id": "a", "approve": True}}])  # fmt: skip
def test_a_request_without_exactly_one_of_prompt_or_decision_is_invalid(
    payload, tmp_path, monkeypatch
):
    model = ScriptedModel()
    hub = build_hub(tmp_path, model)
    monkeypatch.setattr(entrypoint, "get_hub", lambda: hub.hub)

    [error] = invoke(payload, headers={ACTOR: "operator-a"})

    assert error.kind == "InvalidRequest"
    assert model.messages == []  # the model was never called


def test_a_deployed_request_without_an_actor_header_is_refused(tmp_path, monkeypatch):
    model = ScriptedModel([say("never sent")])
    hub = build_hub(tmp_path, model)
    monkeypatch.setattr(entrypoint, "get_hub", lambda: hub.hub)

    [error] = invoke({"prompt": "Status?"})

    assert error.kind == "InvalidRequest"
    assert "actor" in error.message
    assert model.messages == []


def test_a_headerless_deployed_decision_cannot_resume_a_pending_write(tmp_path, monkeypatch):
    model = ScriptedModel([call("stop_channel", "use-1", channel_id="ch-1")], [say("Stopped.")])
    hub = build_hub(tmp_path, model)
    monkeypatch.setattr(entrypoint, "get_hub", lambda: hub.hub)
    [*_, approval] = invoke({"prompt": "Stop ch-1."}, headers={ACTOR: "operator-a"})
    decision = {"decision": {"approval_id": approval.approval_id, "approve": True}}

    [error] = invoke(decision)

    assert error.kind == "InvalidRequest"
    assert hub.pack.approvals == []


def test_local_mode_runs_a_headerless_request_as_the_local_operator(tmp_path, monkeypatch):
    hub = build_hub(tmp_path, ScriptedModel([say("Healthy.")]), local_mode=True)
    monkeypatch.setattr(entrypoint, "get_hub", lambda: hub.hub)

    [answer] = invoke({"prompt": "Status?"}, session=None)

    assert answer.type == "final_answer"
    assert answer.session_id == entrypoint.LOCAL_SESSION


def test_an_unexpected_failure_streams_a_safe_error(monkeypatch):
    def broken():
        raise RuntimeError("secret detail")

    monkeypatch.setattr(entrypoint, "get_hub", broken)

    [error] = invoke({"prompt": "x"})

    assert error.kind == "UnexpectedFailure"
    assert "secret detail" not in json.dumps(error.model_dump(mode="json"))


def test_shared_sessions_require_a_shared_signing_key():
    with pytest.raises(ValidationError, match="APPROVAL_SIGNING_KEY"):
        HubSettings(memory_id="memory-1", approval_signing_key="")

    assert HubSettings(memory_id="memory-1", approval_signing_key="k").memory_id == "memory-1"
