"""
Run one Hydrolix subagent, with the bounds every subagent shares:

- only the Hydrolix tools it needs, each refused unless it stays on HYDROLIX_TABLE;
- the request's tool budget, shared with the orchestrator and the other subagents;
- the request's deadline, which started when the request arrived: the secret read, the
  MCP start, the tool listing and the agent run all count against it.
"""

import asyncio
import contextvars
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from strands_tools import calculator, current_time

from src.settings.runtime_settings import load_runtime_settings
from src.utils import get_request_context, process_agent_stream
from src.utils.bound_hydrolix_tools import BoundHydrolixTools, expose_bounded_tools
from src.utils.record_executed_queries import RecordExecutedQueries
from src.utils.request_context import REQUEST_TIMEOUT_SECONDS


def _get_hydrolix_mcp_env() -> dict:
    """Get Hydrolix configuration from AWS Secrets Manager."""
    secret_arn = os.getenv("HYDROLIX_SECRET_ARN")
    if not secret_arn:
        raise ValueError("HYDROLIX_SECRET_ARN environment variable not set")

    secrets_region = os.getenv("AWS_REGION", "us-east-1")
    # Short timeouts: a worker left behind at the request deadline must still end soon.
    quick = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
    secrets_client = boto3.client("secretsmanager", region_name=secrets_region, config=quick)

    secret_response = secrets_client.get_secret_value(SecretId=secret_arn)
    secret_data = json.loads(secret_response["SecretString"])

    return {
        "HYDROLIX_HOST": secret_data.get("HYDROLIX_HOST"),
        "HYDROLIX_PORT": secret_data.get("HYDROLIX_PORT", "8088"),
        "HYDROLIX_USER": secret_data.get("HYDROLIX_USER"),
        "HYDROLIX_PASSWORD": secret_data.get("HYDROLIX_PASSWORD"),
    }


# The pinned mcp_hydrolix server (a package, so run as a module).
MCP_SERVER_COMMAND = ("python", "-m", "mcp_hydrolix.main")
# Writes its own PID to argv[1], then becomes the server (exec keeps the PID), started as
# `python -X hydrolix_run=<argv[2]> …`: CPython ignores unknown -X options, so the run's nonce
# stays in the server's command line. mcp's stdio_client starts it in a new session, so the
# PID also names its process group. The deadline's fallback kills that group only after
# checking both, so a stale PID file never signals someone else's process.
PID_SHIM = (
    "import os, sys; open(sys.argv[1], 'w').write(str(os.getpid())); "
    "os.execvp(sys.argv[3], [sys.argv[3], '-X', 'hydrolix_run=' + sys.argv[2], *sys.argv[4:]])"
)


def create_hydrolix_mcp_client(pid_file: str, nonce: str) -> MCPClient:
    """The Hydrolix MCP server over stdio, with the secret's settings in its environment."""
    mcp_env = _get_hydrolix_mcp_env()
    python, *_ = MCP_SERVER_COMMAND
    command, args = python, ["-c", PID_SHIM, pid_file, nonce, *MCP_SERVER_COMMAND]
    seconds_left = get_request_context().tool_budget.seconds_left()
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command=command,
                args=args,
                env={**mcp_env, "PYTHONPATH": os.path.join(os.getcwd(), "src/mcp")},
            )
        ),
        # Starting can't outlast the request: then stop() never waits on a lost start.
        startup_timeout=max(1, math.ceil(seconds_left)),
    )


# After the deadline. Stopping the client already waits for its MCP child to end (mcp's
# stdio_client: 2 s to exit, then SIGTERM, then SIGKILL). This is only for the worker to
# return from the call that failed. A worker blocked elsewhere (a model call, a secret
# read) is not waited for: it ends when that call returns, and its tool calls are refused.
JOIN_AFTER_STOP_SECONDS = 1


class SubagentRun:
    """One run's MCP client, so the request deadline can end it from outside the worker.

    A Python thread can't be killed, but the call it is blocked on can be: stopping the
    MCP client terminates its stdio child, which fails a pending list_tools_sync or tool
    call, and the worker returns. Exactly one of the worker and the deadline stops the
    client, and the deadline only stops a client that has finished starting.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: Any = None
        self._started = False
        self._stopped = False
        self.abandoned = False
        handle, self.pid_file = tempfile.mkstemp(prefix="hydrolix-mcp-", suffix=".pid")
        self.nonce = uuid.uuid4().hex
        os.close(handle)

    def start(self, client: Any) -> bool:
        """Start the client unless the run was abandoned; False means don't use it."""
        with self._lock:
            if self.abandoned:
                return False
            self._client = client
        client.start()
        with self._lock:
            self._started = True
            if not self.abandoned:
                return True
        self.stop()  # abandoned while starting: the deadline left the stop to us
        return False

    def abandon(self) -> None:
        """The deadline: no more work, and end a started client now."""
        with self._lock:
            self.abandoned = True
            started = self._started
        if started:
            self.stop()

    def stop(self) -> None:
        with self._lock:
            if self._stopped or self._client is None:
                return
            self._stopped = True
        try:
            self._client.stop(None, None, None)
        except Exception as error:
            # The class only, as everywhere here; then end the child directly.
            print(f"⚠️ MCP client stop failed ({type(error).__name__}); killing its process")
            kill_owned_process_group(self.pid_file, self.nonce)
        finally:
            Path(self.pid_file).unlink(missing_ok=True)


def kill_owned_process_group(pid_file: str, nonce: str) -> None:
    """SIGKILL the run's MCP server group, but only a process that is provably that server:
    it leads its own group and its command line carries this run's nonce. A PID the kernel
    has given to another process fails those checks and is never signalled."""
    try:
        pid = int(Path(pid_file).read_text().strip())
        if os.getpgid(pid) != pid or f"hydrolix_run={nonce}" not in command_line(pid):
            print("ℹ️ MCP process already exited (its PID is not this run's server)")
            return
        os.killpg(pid, signal.SIGKILL)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ℹ️ MCP process already exited ({type(error).__name__})")


def command_line(pid: int) -> str:
    """The process's command line: /proc on Linux (the image has no ps), ps elsewhere."""
    if sys.platform.startswith("linux"):
        return (
            Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        )
    listing = subprocess.run(  # noqa: S603 - a fixed program and an integer PID
        ["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5
    )
    return listing.stdout


def run_hydrolix_subagent(agent_name: str, system_prompt: str, question: str) -> str:
    """The subagent's answer, or a short reason it has none, within the request's deadline.

    Setup is synchronous (Secrets Manager, the MCP process), so the whole run goes to a
    worker thread and this waits only for the time the request has left. A run still going
    at the deadline is abandoned: its tool calls are refused from then on (ToolCallBudget),
    so it stops at its next call, and its answer is never used.
    """
    budget = get_request_context().tool_budget
    stopped = (
        f"The {agent_name} analysis stopped: this request's {REQUEST_TIMEOUT_SECONDS}-second "
        "limit was reached. Ask a narrower question, for example a shorter time range."
    )
    seconds_left = budget.seconds_left()
    if seconds_left <= 0:
        return stopped
    answers: list[str] = []
    request = contextvars.copy_context()  # the worker sees this request's context
    run = SubagentRun()

    def work() -> None:
        answers.append(_run_subagent(agent_name, system_prompt, question, run))

    worker = threading.Thread(target=request.run, args=(work,), name=agent_name, daemon=True)
    worker.start()
    worker.join(seconds_left)
    if worker.is_alive() or not answers:
        print(f"⏱️ Subagent {agent_name} stopped at the request deadline")
        run.abandon()
        worker.join(JOIN_AFTER_STOP_SECONDS)
        return stopped
    return answers[0]


def _run_subagent(agent_name: str, system_prompt: str, question: str, run: SubagentRun) -> str:
    settings = load_runtime_settings()
    budget = get_request_context().tool_budget
    try:
        hydrolix_mcp = create_hydrolix_mcp_client(run.pid_file, run.nonce)
        if not run.start(hydrolix_mcp):
            return f"The {agent_name} analysis was abandoned at the request deadline."
        try:
            hydrolix_tools = expose_bounded_tools(hydrolix_mcp.list_tools_sync())
            agent = Agent(
                model=BedrockModel(model_id=settings.agent_model_id),
                system_prompt=system_prompt,
                tools=[*hydrolix_tools, current_time, calculator],
                hooks=[
                    budget,
                    BoundHydrolixTools(settings.hydrolix_table),
                    RecordExecutedQueries(agent_name, question),
                ],
                callback_handler=None,
            )
            answer = asyncio.run(process_agent_stream(agent, question, agent_name=agent_name))
        finally:
            run.stop()
    except Exception as error:
        # The class name only: an exception message can quote the question or the data.
        print(f"❌ Subagent {agent_name} failed: {type(error).__name__}")
        return f"The {agent_name} analysis failed ({type(error).__name__}). Retry."
    finally:
        Path(run.pid_file).unlink(missing_ok=True)
    if not answer and budget.spent:
        return budget.spent_message
    return answer or f"The {agent_name} analysis returned no answer."
