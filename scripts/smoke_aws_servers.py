"""Probe each converted MCP sample through two read-only live calls.

Every sample is probed, even after one fails, and each gets one line: `ok`, or `FAIL` with
the step that failed and the error class and message. The whole run is bounded by
TIMEOUT_SECONDS, the same limit `just doctor aws` gives it; the exit status is 1 on any
failure.
"""

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 180
HealthArguments = Callable[[dict[str, Any], dict[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class AwsSmokeCase:
    sample: str
    list_tool: str
    health_tool: str
    build_health_arguments: HealthArguments


def require_environment(environ: dict[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set in the root .env")
    return value


def build_cmcd_health_arguments(listed: dict[str, Any], _environ: dict[str, str]) -> dict[str, Any]:
    session_ids = listed.get("session_ids", [])
    if not session_ids:
        raise RuntimeError("cmcd listed no sessions in the last 24 hours")
    return {"time_range": "-24h", "cmcd_sid": session_ids[0]}


def build_mediaconnect_health_arguments(
    listed: dict[str, Any], environ: dict[str, str]
) -> dict[str, Any]:
    flow_arn = require_environment(environ, "MEDIACONNECT_FLOW_ARN")
    visible = {flow.get("flow_arn") for flow in listed.get("flows", [])}
    if flow_arn not in visible:
        raise RuntimeError("MEDIACONNECT_FLOW_ARN was not returned by list_flows")
    return {"flow_arn": flow_arn, "hours_back": 1}


def build_medialive_health_arguments(
    listed: dict[str, Any], environ: dict[str, str]
) -> dict[str, Any]:
    channel_id = require_environment(environ, "MEDIALIVE_CHANNEL_ID")
    visible = {channel.get("channel_id") for channel in listed.get("items", [])}
    if channel_id not in visible:
        raise RuntimeError("MEDIALIVE_CHANNEL_ID was not returned by list_channels")
    return {"channel_id": channel_id, "hours_back": 1}


AWS_SMOKE_CASES = (
    AwsSmokeCase(
        "cmcd",
        "list_session_and_content_ids",
        "analyze_buffer_events",
        build_cmcd_health_arguments,
    ),
    AwsSmokeCase(
        "mediaconnect",
        "list_flows",
        "check_flow_issues",
        build_mediaconnect_health_arguments,
    ),
    AwsSmokeCase(
        "medialive",
        "list_channels",
        "check_channel_issues",
        build_medialive_health_arguments,
    ),
)


def build_child_environment(environ: dict[str, str]) -> dict[str, str]:
    child = dict(environ)
    child.update(
        {
            "ALLOW_WRITES": "false",
            "AWS_EC2_METADATA_DISABLED": "true",
            "DEMO": "false",
        }
    )
    return child


def build_server_parameters(case: AwsSmokeCase, environ: dict[str, str]) -> StdioServerParameters:
    return StdioServerParameters(
        command="just",
        args=["run", case.sample],
        env=build_child_environment(environ),
        cwd=REPOSITORY_ROOT,
    )


def decode_result(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if isinstance(structured.get("result"), list):
            return {"items": structured["result"]}
        return structured
    for content in result.content:
        text = getattr(content, "text", None)
        if not text:
            continue
        payload = json.loads(text)
        return {"items": payload} if isinstance(payload, list) else payload
    raise RuntimeError("tool returned no JSON payload")


def require_read_only_tools(tools: Any, case: AwsSmokeCase) -> None:
    by_name = {tool.name: tool for tool in tools.tools}
    for name in (case.list_tool, case.health_tool):
        tool = by_name.get(name)
        if tool is None:
            raise RuntimeError(f"{case.sample} did not register read tool {name}")
        if not tool.annotations or not tool.annotations.readOnlyHint:
            raise RuntimeError(f"{case.sample}.{name} is not marked read-only")
    writable = [
        tool.name
        for tool in tools.tools
        if not tool.annotations or not tool.annotations.readOnlyHint
    ]
    if writable:
        raise RuntimeError(f"{case.sample} registered writable tools: {', '.join(writable)}")


class ToolCallFailed(RuntimeError):
    """The server answered the tool call with an MCP error."""


@dataclass(frozen=True)
class ProbeResult:
    sample: str
    step: str  # the tool being called, or "startup" before the first call
    error: BaseException | None = None

    def line(self) -> str:
        if self.error is None:
            return f"ok   {self.sample:<14} {self.step}"
        message = " ".join(str(self.error).split())[:300] or "(no message)"
        return f"FAIL {self.sample:<14} {self.step:<30} {type(self.error).__name__}: {message}"


async def call_read_tool(
    session: ClientSession, sample: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    if result.isError:
        texts = [getattr(content, "text", "") for content in result.content]
        raise ToolCallFailed(" ".join(text for text in texts if text) or "MCP error result")
    return decode_result(result)


async def verify_session(
    session: ClientSession,
    case: AwsSmokeCase,
    environ: dict[str, str],
    progress: dict[str, str] | None = None,
) -> None:
    progress = {} if progress is None else progress
    progress["step"] = "startup"
    await session.initialize()
    tools = await session.list_tools()
    require_read_only_tools(tools, case)
    progress["step"] = case.list_tool
    listed = await call_read_tool(session, case.sample, case.list_tool, {})
    health_arguments = case.build_health_arguments(listed, environ)
    progress["step"] = case.health_tool
    await call_read_tool(session, case.sample, case.health_tool, health_arguments)


async def verify_server(
    case: AwsSmokeCase, environ: dict[str, str], progress: dict[str, str]
) -> None:
    parameters = build_server_parameters(case, environ)
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await verify_session(session, case, environ, progress)


def innermost(error: BaseException) -> BaseException:
    """The stdio client wraps a failure in task-group exception groups; report the cause."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


async def probe_all_servers(
    environ: dict[str, str],
    *,
    verify: Callable[..., Any] = verify_server,
    cases: tuple[AwsSmokeCase, ...] = AWS_SMOKE_CASES,
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> list[ProbeResult]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    results = []
    for case in cases:
        progress = {"step": "startup"}
        remaining = deadline - loop.time()
        try:
            if remaining <= 0:
                raise TimeoutError(f"not started: the {timeout_seconds:g} s limit was used up")
            await asyncio.wait_for(verify(case, environ, progress), remaining)
        except TimeoutError as error:
            reason = str(error) or f"the probe exceeded its {timeout_seconds:g} s limit"
            results.append(ProbeResult(case.sample, progress["step"], TimeoutError(reason)))
        except Exception as error:  # boundary: one line per sample, never a traceback
            results.append(ProbeResult(case.sample, progress["step"], innermost(error)))
        else:
            results.append(ProbeResult(case.sample, f"{case.list_tool} -> {case.health_tool}"))
    return results


def main() -> int:
    results = asyncio.run(probe_all_servers(dict(os.environ)))
    for result in results:
        print(result.line())
    if any(result.error for result in results):
        print("AWS smoke failed. Fix the FAIL lines above, then run `just smoke aws` again.")
        return 1
    print("AWS smoke passed with read-only tools.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
