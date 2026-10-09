"""Hydrolix runtime: the actor is a verified identity and logs carry no content.

These run the real entrypoint (app.agent_invocation) with the model, memory and stream
replaced by fakes. `strands_tools` is not a workspace dependency, so it is stubbed.
"""

import asyncio
import importlib
import json
import sys
import time
import types
from pathlib import Path

import jwt
import pytest

AGENT_DIRECTORY = (
    Path(__file__).resolve().parents[2]
    / "samples/hydrolix/cdk-hydrolix-data-assistant-agentcore-strands"
    / "hydrolix-data-assistant-agentcore-strands"
)
ISSUER = "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE"
CLIENT = "example-app-client"
SECRET_PROMPT = "PROMPT-TEXT-THAT-MUST-NOT-BE-LOGGED"
SECRET_ANSWER = "ANSWER-TEXT-THAT-MUST-NOT-BE-LOGGED"


def token(sub: str, **overrides) -> str:
    claims = {"sub": sub, "iss": ISSUER, "client_id": CLIENT, "exp": time.time() + 600}
    claims |= overrides
    # AgentCore verifies the signature before the request reaches the container.
    return "Bearer " + jwt.encode(claims, "test-only-key-not-a-secret-32-bytes", "HS256")


def memory_hooks(agent) -> list:
    """The agent's memory hooks; every agent also counts against the request's tool budget."""
    return [hook for hook in agent.hooks if hasattr(hook, "actor_id")]


class FakeAgent:
    """Records what the entrypoint built and streams one answer."""

    built: list["FakeAgent"] = []

    def __init__(self, *, messages, hooks, **_):
        self.messages, self.hooks = messages, hooks
        FakeAgent.built.append(self)

    async def stream_async(self, _prompt):
        yield {"data": SECRET_ANSWER}


class OfflineMemoryClient:
    """The memory hook's AgentCore client, offline. A real one resolves AWS credentials when
    it is built, down to the EC2 metadata endpoint, which off AWS costs about a second per
    request and makes the test reach the network."""

    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_conversation(self, **kwargs) -> None:
        self.saved.append(kwargs)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("MEMORY_ID", "example-memory")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("HYDROLIX_TABLE", "video.cmcd")
    stub = types.ModuleType("strands_tools")
    for tool in ("calculator", "current_time"):
        setattr(stub, tool, object())
    monkeypatch.setitem(sys.modules, "strands_tools", stub)
    monkeypatch.syspath_prepend(str(AGENT_DIRECTORY))
    monkeypatch.chdir(AGENT_DIRECTORY)
    for name in [name for name in sys.modules if name == "app" or name.startswith("src")]:
        monkeypatch.delitem(sys.modules, name)
    module = importlib.import_module("app")
    identity = importlib.import_module("src.utils.identify_caller")
    monkeypatch.setattr(identity, "CONTAINER_OWNER", identity.ContainerOwner())
    memory_reads: list[tuple[str, str]] = []

    def read_memory(_memory_id, actor_id, session_id, _k):
        memory_reads.append((actor_id, session_id))
        return []

    monkeypatch.setattr(module, "get_agentcore_memory_messages", read_memory)
    hooks = importlib.import_module("src.utils.MemoryHookProvider")
    monkeypatch.setattr(hooks, "MemoryClient", OfflineMemoryClient)
    monkeypatch.setattr(module, "BedrockModel", lambda **_: object())
    monkeypatch.setattr(module, "Agent", FakeAgent)
    FakeAgent.built = []
    module.memory_reads = memory_reads
    module.identity = identity
    return module


def jwt_mode(app, monkeypatch):
    settings = app.runtime_settings.model_copy(
        update={"hydrolix_jwt_issuer": ISSUER, "hydrolix_jwt_allowed_clients": CLIENT}
    )
    monkeypatch.setattr(app, "runtime_settings", settings)


def invoke(app, payload, *, session, authorization=None):
    headers = {"Authorization": authorization} if authorization else {}
    context = types.SimpleNamespace(session_id=session, request_headers=headers)

    async def collect():
        return [json.loads(chunk) async for chunk in app.agent_invocation(payload, context)]

    return asyncio.run(collect())


def test_jwt_mode_refuses_a_request_without_a_valid_token(app, monkeypatch):
    jwt_mode(app, monkeypatch)
    payload = {"prompt": SECRET_PROMPT, "user_id": "alice", "session_id": "s" * 40}

    for authorization in (None, token("alice", client_id="another-client")):
        [refusal] = invoke(app, payload, session="s" * 40, authorization=authorization)
        assert "access token" in refusal["error"]

    assert FakeAgent.built == [] and app.memory_reads == []


def test_the_actor_is_the_token_subject_and_the_session_is_the_runtime_session(app, monkeypatch):
    jwt_mode(app, monkeypatch)
    payload = {"prompt": SECRET_PROMPT, "user_id": "bob", "session_id": "payload-session"}

    invoke(
        app, payload, session="alice-runtime-session-0000000000000", authorization=token("alice")
    )

    assert app.memory_reads == [("alice", "alice-runtime-session-0000000000000")]
    [agent] = FakeAgent.built
    [hook] = memory_hooks(agent)
    assert (hook.actor_id, hook.session_id) == ("alice", "alice-runtime-session-0000000000000")


def test_another_user_cannot_resume_a_session_and_a_recycled_one_stays_per_actor(app, monkeypatch):
    jwt_mode(app, monkeypatch)
    session = "alice-runtime-session-0000000000000"
    invoke(app, {"prompt": "first"}, session=session, authorization=token("alice"))

    # Same microVM: the session belongs to alice, so bob's request is refused.
    [refusal] = invoke(app, {"prompt": "second"}, session=session, authorization=token("bob"))
    assert "another user" in refusal["error"]
    assert app.memory_reads == [("alice", session)]

    # The microVM was recycled and bob reuses the id: he only reaches his own history.
    monkeypatch.setattr(app.identity, "CONTAINER_OWNER", app.identity.ContainerOwner())
    invoke(app, {"prompt": "third"}, session=session, authorization=token("bob"))
    assert app.memory_reads == [("alice", session), ("bob", session)]


def test_iam_mode_turns_memory_off_and_says_so(app, capsys):
    payload = {"prompt": SECRET_PROMPT, "user_id": "alice"}

    chunks = invoke(app, payload, session="iam-runtime-session-00000000000000")

    assert "Memory is off" in chunks[0]["notice"]
    assert app.memory_reads == []
    assert memory_hooks(FakeAgent.built[0]) == [] and FakeAgent.built[0].messages == []
    assert "memory off" in capsys.readouterr().out


def test_a_request_without_a_runtime_session_is_refused(app):
    [refusal] = invoke(app, {"prompt": "x"}, session=None)
    assert "session" in refusal["error"]
    assert FakeAgent.built == []


def test_logs_carry_no_prompt_answer_user_or_session(app, monkeypatch, capsys):
    jwt_mode(app, monkeypatch)
    session = "SESSION-ID-THAT-MUST-NOT-BE-LOGGED-0000"
    subject = "USER-ID-THAT-MUST-NOT-BE-LOGGED"

    invoke(app, {"prompt": SECRET_PROMPT}, session=session, authorization=token(subject))
    [hook] = memory_hooks(FakeAgent.built[0])
    hook.memory_client = types.SimpleNamespace(save_conversation=lambda **_: None)
    hook.on_message_added(
        types.SimpleNamespace(
            agent=types.SimpleNamespace(
                messages=[{"role": "assistant", "content": [{"text": SECRET_ANSWER}]}]
            )
        )
    )

    logged = capsys.readouterr().out
    assert "prompt length=" in logged and "saved one assistant message" in logged
    for secret in (SECRET_PROMPT, SECRET_ANSWER, session, subject):
        assert secret not in logged


def test_the_subagent_stream_logs_no_question_sql_or_answer(app, monkeypatch, capsys):
    stream = importlib.import_module("src.utils.stream_processor")
    sql = "SELECT secret_column FROM video.cmcd WHERE viewer = 'SQL-THAT-MUST-NOT-BE-LOGGED'"
    tool_use = {"toolUseId": "tool-1", "name": "run_select_query"}

    class Subagent:
        async def stream_async(self, _query):
            yield {"event": {"contentBlockStart": {"start": {"toolUse": tool_use}}}}
            yield {"current_tool_use": {"input": json.dumps({"query": sql, "purpose": "x"})}}
            yield {"event": {"contentBlockStop": {}}}
            yield {"data": SECRET_ANSWER}

    importlib.import_module("src.utils.request_context").set_request_context("prompt-1")
    answer = asyncio.run(stream.process_agent_stream(Subagent(), SECRET_PROMPT, "qoe_agent"))

    logged = capsys.readouterr().out
    assert answer == SECRET_ANSWER
    assert "query length=" in logged
    for secret in (SECRET_PROMPT, SECRET_ANSWER, "SQL-THAT-MUST-NOT-BE-LOGGED"):
        assert secret not in logged
