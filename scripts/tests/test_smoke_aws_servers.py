import asyncio
from types import SimpleNamespace

import pytest
import smoke_aws_servers as smoke


class FakeSession:
    def __init__(self, payloads, *, writable_tool=None):
        self.payloads = payloads
        self.calls = []
        self.writable_tool = writable_tool

    async def initialize(self):
        return None

    async def list_tools(self):
        tools = [
            SimpleNamespace(
                name=name,
                annotations=SimpleNamespace(readOnlyHint=True),
            )
            for name in self.payloads
        ]
        if self.writable_tool:
            tools.append(
                SimpleNamespace(
                    name=self.writable_tool,
                    annotations=SimpleNamespace(readOnlyHint=False),
                )
            )
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            isError=False,
            structuredContent=self.payloads[name],
            content=[],
        )


def test_cmcd_calls_one_list_then_one_health_read():
    case = smoke.AWS_SMOKE_CASES[0]
    session = FakeSession(
        {
            case.list_tool: {"session_ids": ["session-1"]},
            case.health_tool: {"total_events": 3},
        }
    )

    asyncio.run(smoke.verify_session(session, case, {}))

    assert session.calls == [
        ("list_session_and_content_ids", {}),
        ("analyze_buffer_events", {"time_range": "-24h", "cmcd_sid": "session-1"}),
    ]


@pytest.mark.parametrize(
    ("case", "environ", "listed", "expected_arguments"),
    [
        (
            smoke.AWS_SMOKE_CASES[1],
            {"MEDIACONNECT_FLOW_ARN": "arn:aws:mediaconnect:region:account:flow:1"},
            {"flows": [{"flow_arn": "arn:aws:mediaconnect:region:account:flow:1"}]},
            {"flow_arn": "arn:aws:mediaconnect:region:account:flow:1", "hours_back": 1},
        ),
        (
            smoke.AWS_SMOKE_CASES[2],
            {"MEDIALIVE_CHANNEL_ID": "1234567"},
            {"result": [{"channel_id": "1234567"}]},
            {"channel_id": "1234567", "hours_back": 1},
        ),
    ],
)
def test_configured_resource_is_listed_before_health_read(
    case, environ, listed, expected_arguments
):
    session = FakeSession(
        {
            case.list_tool: listed,
            case.health_tool: {"status": "HEALTHY"},
        }
    )

    asyncio.run(smoke.verify_session(session, case, environ))

    assert session.calls == [
        (case.list_tool, {}),
        (case.health_tool, expected_arguments),
    ]


def test_probe_rejects_any_registered_write_tool():
    case = smoke.AWS_SMOKE_CASES[1]
    session = FakeSession(
        {
            case.list_tool: {"flows": []},
            case.health_tool: {},
        },
        writable_tool="stop_flow",
    )

    with pytest.raises(RuntimeError, match="registered writable tools: stop_flow"):
        asyncio.run(smoke.verify_session(session, case, {}))

    assert session.calls == []


def test_probe_forces_live_read_only_mode():
    environment = smoke.build_child_environment(
        {"ALLOW_WRITES": "true", "DEMO": "1", "AWS_PROFILE": "sandbox"}
    )

    assert environment["ALLOW_WRITES"] == "false"
    assert environment["DEMO"] == "false"
    assert environment["AWS_PROFILE"] == "sandbox"


def test_missing_or_unlisted_target_fails_before_health_read():
    case = smoke.AWS_SMOKE_CASES[2]
    session = FakeSession(
        {
            case.list_tool: {"items": [{"channel_id": "7654321"}]},
            case.health_tool: {},
        }
    )

    with pytest.raises(RuntimeError, match="MEDIALIVE_CHANNEL_ID was not returned"):
        asyncio.run(
            smoke.verify_session(
                session,
                case,
                {"MEDIALIVE_CHANNEL_ID": "1234567"},
            )
        )

    assert session.calls == [(case.list_tool, {})]


# Readable failures and one overall limit.
def run_probe(verify, *, timeout_seconds=5.0):
    return asyncio.run(smoke.probe_all_servers({}, verify=verify, timeout_seconds=timeout_seconds))


def test_every_sample_is_probed_and_each_failure_is_one_line(capsys, monkeypatch):
    async def verify(case, environ, progress):
        if case.sample == "mediaconnect":
            progress["step"] = case.list_tool
            # What stdio_client actually raises: the cause, nested in task-group groups.
            raise ExceptionGroup(
                "unhandled errors in a TaskGroup",
                [ExceptionGroup("inner", [smoke.ToolCallFailed("AccessDenied: not allowed")])],
            )

    real_probe = smoke.probe_all_servers
    monkeypatch.setattr(smoke, "probe_all_servers", lambda environ: real_probe({}, verify=verify))
    assert smoke.main() == 1

    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines[:3]] == [
        ["ok", "cmcd"],
        ["FAIL", "mediaconnect"],
        ["ok", "medialive"],
    ]
    assert "list_flows" in lines[1]
    assert "ToolCallFailed: AccessDenied: not allowed" in lines[1]
    assert "ExceptionGroup" not in "\n".join(lines) and "Traceback" not in "\n".join(lines)


def test_the_whole_run_is_bounded_and_a_hung_server_is_reported():
    async def verify(case, environ, progress):
        if case.sample == "cmcd":
            progress["step"] = case.health_tool
            await asyncio.sleep(10)

    results = run_probe(verify, timeout_seconds=0.2)

    assert [(r.sample, type(r.error).__name__ if r.error else None) for r in results] == [
        ("cmcd", "TimeoutError"),
        ("mediaconnect", "TimeoutError"),
        ("medialive", "TimeoutError"),
    ]
    assert results[0].step == "analyze_buffer_events"
    assert "not started" in str(results[1].error)


def test_the_probe_limit_matches_doctor():
    import check_prerequisites

    assert smoke.TIMEOUT_SECONDS == 180
    assert check_prerequisites.AWS_PROBE_TIMEOUT_SECONDS > smoke.TIMEOUT_SECONDS


def test_an_mcp_error_result_reports_its_text_not_json():
    class ErrorSession:
        async def call_tool(self, name, arguments):
            text = SimpleNamespace(
                text="ExternalServiceUnavailable: timed out. Next action: retry."
            )
            return SimpleNamespace(isError=True, content=[text])

    with pytest.raises(smoke.ToolCallFailed, match="^ExternalServiceUnavailable: timed out"):
        asyncio.run(
            smoke.call_read_tool(ErrorSession(), "cmcd", "list_session_and_content_ids", {})
        )
