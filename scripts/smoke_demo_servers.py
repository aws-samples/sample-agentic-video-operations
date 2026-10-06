"""Start each converted sample over MCP stdio and prove one fixture read works."""

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SMOKE_GUARD = Path(__file__).resolve().parent / "smoke_guard"


@dataclass(frozen=True)
class SmokeCase:
    sample: str
    tool: str
    expected_fragment: str


SMOKE_CASES = (
    SmokeCase("cmcd", "analyze_buffer_events", "low_buffer_count"),
    SmokeCase("mediaconnect", "list_flows", "flows"),
    SmokeCase("medialive", "list_channels", "channel_id"),
)


def build_child_environment(environ: dict[str, str]) -> dict[str, str]:
    child = dict(environ)
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
    ):
        child.pop(name, None)
    python_path = child.get("PYTHONPATH", "")
    child.update(
        {
            "ALLOW_WRITES": "false",
            "AWS_EC2_METADATA_DISABLED": "true",
            "DEMO": "1",
            "PYTHONPATH": f"{SMOKE_GUARD}{os.pathsep}{python_path}".rstrip(os.pathsep),
        }
    )
    return child


def build_server_parameters(
    case: SmokeCase,
    temporary_env: Path,
    environ: dict[str, str],
) -> StdioServerParameters:
    return StdioServerParameters(
        command="just",
        args=["--dotenv-path", str(temporary_env), "run", case.sample],
        env=build_child_environment(environ),
        cwd=REPOSITORY_ROOT,
    )


async def verify_session(session: ClientSession, case: SmokeCase) -> None:
    await session.initialize()
    tools = await session.list_tools()
    names = {tool.name for tool in tools.tools}
    if case.tool not in names:
        raise RuntimeError(f"{case.sample} did not register read tool {case.tool}")

    result = await session.call_tool(case.tool, {})
    if result.isError:
        raise RuntimeError(f"{case.sample}.{case.tool} failed: {result.model_dump_json()}")
    payload = result.model_dump_json()
    if case.expected_fragment not in payload:
        raise RuntimeError(
            f"{case.sample}.{case.tool} did not return fixture evidence "
            f"{case.expected_fragment!r}: {payload}"
        )


async def verify_server(case: SmokeCase, temporary_env: Path) -> None:
    parameters = build_server_parameters(case, temporary_env, os.environ)
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await verify_session(session, case)
    print(f"ok   {case.sample:<16} {case.tool}")


async def verify_all_servers(temporary_env: Path) -> None:
    for case in SMOKE_CASES:
        await verify_server(case, temporary_env)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="video-ops-demo-smoke-") as temporary:
        temporary_env = Path(temporary) / ".env"
        shutil.copyfile(REPOSITORY_ROOT / ".env.example", temporary_env)
        asyncio.run(verify_all_servers(temporary_env))
    print("Demo smoke passed without AWS clients.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
