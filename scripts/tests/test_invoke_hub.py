"""invoke_hub.py sends the actor header, the right payload, and prints each SSE event."""

import io
import json
from types import SimpleNamespace

import invoke_hub
import pytest

OUTPUTS = [
    {
        "OutputKey": "AgentRuntimeArn",
        "OutputValue": "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/MediaOpsHub_x",
    },  # noqa: E501
    {"OutputKey": "AgentEndpointName", "OutputValue": "MediaOpsHubEndpoint_x"},
]


class FakeAgentCore:
    def __init__(self):
        self.hooks, self.calls = [], []
        self.meta = SimpleNamespace(events=SimpleNamespace(register=self.register))

    def register(self, name, handler):
        self.hooks.append((name, handler))

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        body = b'data: {"type": "final_answer", "text": "ok"}\n\n'
        return {"response": SimpleNamespace(iter_lines=lambda: io.BytesIO(body).readlines())}


def run(argv, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    agentcore = FakeAgentCore()
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": OUTPUTS}]})  # noqa: E501
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": agentcore}
    status = invoke_hub.invoke_hub(
        invoke_hub.parse_arguments(argv), create_client=lambda name, **_: clients[name]
    )
    return status, agentcore


def test_a_prompt_is_sent_with_the_actor_header_and_a_long_session_id(monkeypatch, capsys):
    status, agentcore = run(["--actor", "operator-a", "Is 1234567 healthy?"], monkeypatch)

    [call] = agentcore.calls
    assert status == 0
    assert json.loads(call["payload"]) == {"prompt": "Is 1234567 healthy?"}
    assert call["qualifier"] == "MediaOpsHubEndpoint_x"
    assert len(call["runtimeSessionId"]) >= 33
    [(event, add_header)] = agentcore.hooks
    request = SimpleNamespace(headers={})
    add_header(request)
    assert event == "before-sign.bedrock-agentcore.InvokeAgentRuntime"
    assert request.headers == {invoke_hub.ACTOR_HEADER: "operator-a"}
    assert '"final_answer"' in capsys.readouterr().out


def test_a_decision_resumes_the_given_session(monkeypatch):
    argv = ["--actor", "operator-a", "--session", "s" * 40, "--approve", "approval-1"]
    _, agentcore = run(argv, monkeypatch)

    [call] = agentcore.calls
    assert call["runtimeSessionId"] == "s" * 40
    assert json.loads(call["payload"]) == {
        "decision": {"approval_id": "approval-1", "approve": True}
    }  # noqa: E501


def test_a_decision_without_its_session_is_rejected():
    with pytest.raises(SystemExit):
        invoke_hub.parse_arguments(["--actor", "a", "--reject", "approval-1"])


def test_an_aws_failure_is_one_line_and_a_nonzero_exit(monkeypatch, capsys):
    from botocore.exceptions import ClientError

    def denied(**_):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Invoke")

    monkeypatch.setenv("AWS_REGION", "us-west-2")
    agentcore = FakeAgentCore()
    agentcore.invoke_agent_runtime = denied
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": OUTPUTS}]})  # noqa: E501
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": agentcore}

    status = invoke_hub.invoke_hub(
        invoke_hub.parse_arguments(["--actor", "a", "hi"]), create_client=lambda n, **_: clients[n]
    )

    assert status == 1
    assert "AccessDeniedException" in capsys.readouterr().out


def test_a_stack_without_outputs_is_reported_not_a_traceback(monkeypatch, capsys):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": []}]})
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": FakeAgentCore()}

    status = invoke_hub.invoke_hub(
        invoke_hub.parse_arguments(["--actor", "a", "hi"]), create_client=lambda n, **_: clients[n]
    )

    assert status == 1
    assert "Redeploy" in capsys.readouterr().out
