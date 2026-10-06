"""invoke_hydrolix.py: bearer token on a JWT stack, SigV4 on an IAM stack, token never shown."""

import io
import json
from types import SimpleNamespace

import invoke_hydrolix
import pytest

ARN = "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/HydrolixRuntime_x"
OUTPUTS = [
    {"OutputKey": "AgentRuntimeArn", "OutputValue": ARN},
    {"OutputKey": "AgentEndpointName", "OutputValue": "HydrolixEndpoint_x"},
]
PLACEHOLDER_TOKEN = "example-access-token"  # noqa: S105 - test placeholder, not a credential
STREAM = (
    b'data: "{\\"notice\\": \\"Memory is off\\"}\\n"\n\n'
    b'data: "{\\"data\\": \\"Most errors: \\"}\\n"\n\n'
    b'data: "{\\"data\\": \\"POP-1\\"}\\n"\n\n'
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run(argv, monkeypatch, *, inbound_auth, with_token=True):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    if with_token:
        monkeypatch.setenv("HYDROLIX_BEARER_TOKEN", PLACEHOLDER_TOKEN)
    else:
        monkeypatch.delenv("HYDROLIX_BEARER_TOKEN", raising=False)
    outputs = [*OUTPUTS, {"OutputKey": "InboundAuth", "OutputValue": inbound_auth}]
    sigv4_calls, requests = [], []
    agentcore = SimpleNamespace(
        invoke_agent_runtime=lambda **kwargs: sigv4_calls.append(kwargs)
        or {"response": SimpleNamespace(iter_lines=lambda: io.BytesIO(STREAM).readlines())}
    )
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": outputs}]})
    clients = {"cloudformation": cloudformation, "bedrock-agentcore": agentcore}

    def open_url(request):
        requests.append(request)
        return FakeResponse(STREAM)

    status = invoke_hydrolix.invoke_hydrolix(
        invoke_hydrolix.parse_arguments(argv),
        create_client=lambda name, **_: clients[name],
        open_url=open_url,
    )
    return status, sigv4_calls, requests


def test_a_jwt_stack_is_called_over_https_with_the_token_and_no_payload_identity(
    monkeypatch, capsys
):
    status, sigv4_calls, [request] = run(["Top errors?"], monkeypatch, inbound_auth="jwt")

    assert status == 0 and sigv4_calls == []
    assert request.full_url.startswith(
        "https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/"
    )
    assert "/invocations?qualifier=HydrolixEndpoint_x" in request.full_url
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["authorization"] == f"Bearer {PLACEHOLDER_TOKEN}"
    assert len(headers[invoke_hydrolix.SESSION_HEADER.lower()]) >= 33
    sent = json.loads(request.data)
    assert set(sent) == {"prompt", "prompt_uuid"}  # no user_id or session_id to trust
    out = capsys.readouterr().out
    assert "Most errors: POP-1" in out and PLACEHOLDER_TOKEN not in out


def test_a_jwt_stack_without_a_token_sends_nothing(monkeypatch, capsys):
    status, sigv4_calls, requests = run(
        ["Top errors?"], monkeypatch, inbound_auth="jwt", with_token=False
    )

    assert status == 1 and sigv4_calls == [] and requests == []
    assert "HYDROLIX_BEARER_TOKEN" in capsys.readouterr().out


def test_an_iam_stack_uses_sigv4_and_shows_the_memory_off_notice(monkeypatch, capsys):
    status, [call], requests = run(["Top errors?"], monkeypatch, inbound_auth="iam")

    assert status == 0 and requests == []
    assert call["qualifier"] == "HydrolixEndpoint_x"
    assert len(call["runtimeSessionId"]) >= 33
    assert "[notice] Memory is off" in capsys.readouterr().out


def test_a_short_session_id_is_rejected():
    with pytest.raises(SystemExit):
        invoke_hydrolix.parse_arguments(["--session", "short", "hi"])


DISTINCT_TOKEN = "eyJ-distinct-token-that-must-never-print"  # noqa: S105 - test placeholder


@pytest.mark.parametrize("failure", ["http", "url"])
def test_a_failed_call_never_prints_the_bearer_token(failure, monkeypatch, capsys):
    import urllib.error

    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("HYDROLIX_BEARER_TOKEN", DISTINCT_TOKEN)
    outputs = [*OUTPUTS, {"OutputKey": "InboundAuth", "OutputValue": "jwt"}]
    cloudformation = SimpleNamespace(describe_stacks=lambda **_: {"Stacks": [{"Outputs": outputs}]})

    def open_url(request):
        if failure == "http":
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", dict(request.header_items()), None
            )
        raise urllib.error.URLError(f"cannot reach {request.full_url}")

    status = invoke_hydrolix.invoke_hydrolix(
        invoke_hydrolix.parse_arguments(["Top errors?"]),
        create_client=lambda name, **_: {"cloudformation": cloudformation}[name],
        open_url=open_url,
    )

    out = capsys.readouterr()
    assert status == 1
    assert DISTINCT_TOKEN not in out.out + out.err
    assert ("HTTP 401" if failure == "http" else "could not be reached") in out.out
