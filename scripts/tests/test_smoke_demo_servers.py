import asyncio
from types import SimpleNamespace

import pytest
import smoke_demo_servers as smoke


class FakeSession:
    def __init__(self, *, tool="list_flows", payload='{"flows": []}', failed=False):
        self.tool = tool
        self.payload = payload
        self.failed = failed
        self.initialized = False
        self.called = None

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=self.tool)])

    async def call_tool(self, name, arguments):
        self.called = (name, arguments)
        return SimpleNamespace(
            isError=self.failed,
            model_dump_json=lambda: self.payload,
        )


def test_server_parameters_use_just_with_the_temporary_env(tmp_path):
    temporary_env = tmp_path / ".env"
    case = smoke.SmokeCase("mediaconnect", "list_flows", "flows")

    parameters = smoke.build_server_parameters(
        case,
        temporary_env,
        {"AWS_PROFILE": "personal", "PYTHONPATH": "/existing"},
    )

    assert parameters.command == "just"
    assert parameters.args == [
        "--dotenv-path",
        str(temporary_env),
        "run",
        "mediaconnect",
    ]
    assert parameters.cwd == smoke.REPOSITORY_ROOT
    assert parameters.env["DEMO"] == "1"
    assert parameters.env["ALLOW_WRITES"] == "false"
    assert "AWS_PROFILE" not in parameters.env
    assert str(smoke.SMOKE_GUARD) in parameters.env["PYTHONPATH"]


def test_verify_session_initializes_lists_and_calls_one_read_tool():
    session = FakeSession()
    case = smoke.SmokeCase("mediaconnect", "list_flows", "flows")

    asyncio.run(smoke.verify_session(session, case))

    assert session.initialized
    assert session.called == ("list_flows", {})


def test_verify_session_rejects_a_missing_fixture_result():
    session = FakeSession(payload='{"result": []}')
    case = smoke.SmokeCase("mediaconnect", "list_flows", "flows")

    with pytest.raises(RuntimeError, match="did not return fixture evidence"):
        asyncio.run(smoke.verify_session(session, case))
