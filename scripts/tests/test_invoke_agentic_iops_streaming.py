"""invoke_agentic_iops_streaming.py sends the actor header, the right payload, and prints each SSE
event."""

import io
import json
from types import SimpleNamespace

import invoke_agentic_iops_streaming
import pytest

OUTPUTS = [
    {
        "OutputKey": "AgentRuntimeArn",
        "OutputValue": (
            "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/AgenticIopsStreaming_x"
        ),
    },  # noqa: E501
    {"OutputKey": "AgentEndpointName", "OutputValue": "AgenticIopsStreamingEndpoint_x"},
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
    status = invoke_agentic_iops_streaming.invoke_agentic_iops_streaming(
        invoke_agentic_iops_streaming.parse_arguments(argv),
        create_client=lambda name, **_: clients[name],
    )
    return status, agentcore


def test_a_prompt_is_sent_with_the_actor_header_and_a_long_session_id(monkeypatch, capsys):
    status, agentcore = run(["--actor", "operator-a", "Is 1234567 healthy?"], monkeypatch)

    [call] = agentcore.calls
    assert status == 0
    assert json.loads(call["payload"]) == {"prompt": "Is 1234567 healthy?"}
    assert call["qualifier"] == "AgenticIopsStreamingEndpoint_x"
    assert len(call["runtimeSessionId"]) >= 33
    [(event, add_header)] = agentcore.hooks
    request = SimpleNamespace(headers={})
    add_header(request)
    assert event == "before-sign.bedrock-agentcore.InvokeAgentRuntime"
    assert request.headers == {invoke_agentic_iops_streaming.ACTOR_HEADER: "operator-a"}
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
        invoke_agentic_iops_streaming.parse_arguments(["--actor", "a", "--reject", "approval-1"])


def test_an_aws_failure_is_one_line_and_a_nonzero_exit(monkeypatch, capsys):
    from botocore.exceptions import ClientError

    def denied(**_):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Invoke")

    monkeypatch.setenv("AWS_REGION", "us-west-2")
    agentcore = FakeAgentCore()
    agentcore.invoke_agent_runtime = denied
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": OUTPUTS}]})  # noqa: E501
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": agentcore}

    status = invoke_agentic_iops_streaming.invoke_agentic_iops_streaming(
        invoke_agentic_iops_streaming.parse_arguments(["--actor", "a", "hi"]),
        create_client=lambda n, **_: clients[n],
    )

    assert status == 1
    assert "AccessDeniedException" in capsys.readouterr().out


def test_a_stack_without_outputs_is_reported_not_a_traceback(monkeypatch, capsys):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": []}]})
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": FakeAgentCore()}

    status = invoke_agentic_iops_streaming.invoke_agentic_iops_streaming(
        invoke_agentic_iops_streaming.parse_arguments(["--actor", "a", "hi"]),
        create_client=lambda n, **_: clients[n],
    )

    assert status == 1
    assert "Redeploy" in capsys.readouterr().out


JWT_OUTPUTS = [*OUTPUTS, {"OutputKey": "InboundAuth", "OutputValue": "jwt"}]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


PLACEHOLDER_TOKEN = "example-access-token"  # noqa: S105 - test placeholder, not a credential


def run_jwt(argv, monkeypatch, *, with_token=True):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    if with_token:
        monkeypatch.setenv("AGENTIC_IOPS_BEARER_TOKEN", PLACEHOLDER_TOKEN)
    else:
        monkeypatch.delenv("AGENTIC_IOPS_BEARER_TOKEN", raising=False)
    agentcore, requests = FakeAgentCore(), []
    cloudformation = SimpleNamespace(
        describe_stacks=lambda **_: {"Stacks": [{"Outputs": JWT_OUTPUTS}]}
    )
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": agentcore}

    def open_url(request):
        requests.append(request)
        return FakeResponse(b'data: {"type": "final_answer", "text": "ok"}\n\n')

    status = invoke_agentic_iops_streaming.invoke_agentic_iops_streaming(
        invoke_agentic_iops_streaming.parse_arguments(argv),
        create_client=lambda name, **_: clients[name],
        open_url=open_url,
    )
    return status, agentcore, requests


def test_a_jwt_agentic_iops_is_called_over_https_with_the_bearer_token_and_no_actor_header(
    monkeypatch, capsys
):
    status, agentcore, [request] = run_jwt(["--actor", "ignored", "Status?"], monkeypatch)

    assert status == 0
    assert agentcore.calls == [] and agentcore.hooks == []  # no SigV4 call, no actor header
    assert request.full_url == (
        "https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/"
        "arn%3Aaws%3Abedrock-agentcore%3Aus-west-2%3A111122223333%3Aruntime%2FAgenticIopsStreaming_x"
        "/invocations?qualifier=AgenticIopsStreamingEndpoint_x"
    )
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["authorization"] == "Bearer example-access-token"
    assert len(headers[invoke_agentic_iops_streaming.SESSION_HEADER.lower()]) >= 33
    assert invoke_agentic_iops_streaming.ACTOR_HEADER.lower() not in headers
    assert json.loads(request.data) == {"prompt": "Status?"}
    out = capsys.readouterr().out
    assert '"final_answer"' in out and "example-access-token" not in out


def test_a_jwt_agentic_iops_without_a_token_sends_nothing(monkeypatch, capsys):
    status, _, requests = run_jwt(["Status?"], monkeypatch, with_token=False)

    assert status == 1
    assert requests == []
    assert "AGENTIC_IOPS_BEARER_TOKEN" in capsys.readouterr().out


def test_an_iam_agentic_iops_still_needs_an_actor(monkeypatch, capsys):
    status, agentcore = run(["Status?"], monkeypatch)

    assert status == 1
    assert agentcore.calls == []
    assert "--actor" in capsys.readouterr().out
