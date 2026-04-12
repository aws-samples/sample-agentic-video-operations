"""EML MediaLive Agent — consolidated tools, code_mode, session pooling.

15 individual tools → 5 composite tools (~67% schema token reduction).
Follows the EMX pattern: composite dispatch, TOOL_DISPATCH_MAP, smart routing.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from strands import Agent, tool
from strands.models import BedrockModel
import contextlib
import io
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

# Import plain functions (no @tool decorators) from tool modules
from .tools import (
    current_time as _current_time_fn,
    list_channels,
    describe_channel,
    start_channel,
    stop_channel,
    get_channel_metrics,
    get_channel_logs,
    describe_channel_thumbnail,
    describe_schedule,
    create_input_switch_action,
    create_scte35_action,
    create_pause_action,
    create_unpause_action,
    delete_schedule_action,
    create_immediate_input_switch,
)

# Import code interpreter
from .code_interpreter import CodeInterpreterExecutor, SessionPool

# Import monitoring coordinator
from .monitoring.coordinator import MonitoringCoordinator

logger = logging.getLogger(__name__)

# Initialize monitoring coordinator
_monitoring_coordinator = MonitoringCoordinator()

# Configuration
PORT = int(os.environ.get("PORT", "8080"))

# Smart routing threshold — skip Code Interpreter for responses under this size
# Smart routing threshold — use local exec for everything.
# Code Interpreter sessions are unreliable (stale sessions, AccessDenied).
SMALL_RESPONSE_THRESHOLD = 524288  # 512KB

# FastAPI application
app = FastAPI(title="EML MediaLive Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/ping")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# 5 Consolidated Tools (15 → 5 for ~67% schema token reduction)
# ---------------------------------------------------------------------------

@tool
def current_time():
    """Get the current time"""
    return _current_time_fn()


@tool
def channel_management(action: str, channel_id: str = None, pipeline_id: str = "0") -> str:
    """Manage MediaLive channels.

    Args:
        action: One of: list, describe, start, stop, thumbnail
        channel_id: Channel ID (optional, defaults to DEFAULT_CHANNEL_ID)
        pipeline_id: Pipeline ID for thumbnail action (default "0")
    """
    dispatch = {
        "list": lambda: list_channels(),
        "describe": lambda: describe_channel(channel_id),
        "start": lambda: start_channel(channel_id),
        "stop": lambda: stop_channel(channel_id),
        "thumbnail": lambda: describe_channel_thumbnail(channel_id, pipeline_id),
    }
    if action not in dispatch:
        return json.dumps({"error": f"Unknown action '{action}'", "valid_actions": list(dispatch.keys())})
    return dispatch[action]()


@tool
def channel_monitoring(action: str, channel_id: str = None, hours_back: int = 1) -> str:
    """Monitor MediaLive channel health and metrics.

    Args:
        action: One of: metrics, logs
        channel_id: Channel ID (optional, defaults to DEFAULT_CHANNEL_ID)
        hours_back: Hours of data to retrieve (default 1)
    """
    dispatch = {
        "metrics": lambda: get_channel_metrics(channel_id, hours_back),
        "logs": lambda: get_channel_logs(channel_id, hours_back),
    }
    if action not in dispatch:
        return json.dumps({"error": f"Unknown action '{action}'", "valid_actions": list(dispatch.keys())})
    return dispatch[action]()


@tool
def schedule_management(
    action: str,
    channel_id: str = None,
    action_name: str = "",
    input_attachment_name: str = "",
    start_time: str = "",
    splice_event_id: int = 0,
    duration: int = None,
    pipeline_id: str = "PIPELINE_0",
) -> str:
    """Manage MediaLive channel schedules.

    Args:
        action: One of: describe, input_switch, immediate_switch, scte35, pause, unpause, delete
        channel_id: Channel ID (optional, defaults to DEFAULT_CHANNEL_ID)
        action_name: Name for the schedule action (required for create/delete actions)
        input_attachment_name: Input attachment reference (for input_switch, immediate_switch)
        start_time: ISO timestamp for fixed-time actions
        splice_event_id: SCTE-35 splice event ID
        duration: SCTE-35 duration (optional)
        pipeline_id: Pipeline ID for pause/unpause (default PIPELINE_0)
    """
    dispatch = {
        "describe": lambda: describe_schedule(channel_id),
        "input_switch": lambda: create_input_switch_action(channel_id, action_name, input_attachment_name, start_time),
        "immediate_switch": lambda: create_immediate_input_switch(channel_id, action_name, input_attachment_name),
        "scte35": lambda: create_scte35_action(channel_id, action_name, start_time, splice_event_id, duration),
        "pause": lambda: create_pause_action(channel_id, action_name, start_time, pipeline_id),
        "unpause": lambda: create_unpause_action(channel_id, action_name, start_time, pipeline_id),
        "delete": lambda: delete_schedule_action(channel_id, action_name),
    }
    if action not in dispatch:
        return json.dumps({"error": f"Unknown action '{action}'", "valid_actions": list(dispatch.keys())})

    # Validate required params per action
    if action in ("input_switch", "immediate_switch", "scte35", "pause", "unpause", "delete") and not action_name:
        return json.dumps({"error": "action_name is required for this action"})
    if action in ("input_switch", "immediate_switch") and not input_attachment_name:
        return json.dumps({"error": "input_attachment_name is required for this action"})
    if action in ("input_switch", "scte35", "pause", "unpause") and not start_time:
        return json.dumps({"error": "start_time is required for this action"})

    return dispatch[action]()


@tool
def channel_health_monitoring(action: str, channel_id: str = None, hours_back: int = 1, category: str = "") -> str:
    """Monitor MediaLive channel health via CloudWatch (5-category monitoring).

    Args:
        action: One of: all_metrics, category_metrics, check_issues, metrics_table
        channel_id: Channel ID (optional, defaults to DEFAULT_CHANNEL_ID)
        hours_back: Hours of data to retrieve (default 1)
        category: Category name for category_metrics action (channel_health, input_health, output_health, media_health, content_quality)
    """
    from .tools.constants import get_channel_id as _get_cid
    cid = _get_cid(channel_id)

    dispatch = {
        "all_metrics": lambda: _monitoring_coordinator.get_all_metrics(cid, hours_back),
        "category_metrics": lambda: _monitoring_coordinator.get_category_metrics(category, cid, hours_back),
        "check_issues": lambda: _monitoring_coordinator.check_channel_issues(cid, hours_back),
        "metrics_table": lambda: _monitoring_coordinator.get_metrics_table(cid, hours_back),
    }
    if action not in dispatch:
        return json.dumps({"error": f"Unknown action '{action}'", "valid_actions": list(dispatch.keys())})
    result = dispatch[action]()
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Code Mode — Tool Dispatch Map + code_mode tool
# ---------------------------------------------------------------------------

TOOL_DISPATCH_MAP: dict[str, callable] = {
    # Channel management
    "list_channels": lambda **kw: list_channels(),
    "describe_channel": lambda **kw: describe_channel(**kw),
    "start_channel": lambda **kw: start_channel(**kw),
    "stop_channel": lambda **kw: stop_channel(**kw),
    "describe_channel_thumbnail": lambda **kw: describe_channel_thumbnail(**kw),
    # Channel monitoring
    "get_channel_metrics": lambda **kw: get_channel_metrics(**kw),
    "get_channel_logs": lambda **kw: get_channel_logs(**kw),
    # Schedule management
    "describe_schedule": lambda **kw: describe_schedule(**kw),
    "create_input_switch_action": lambda **kw: create_input_switch_action(**kw),
    "create_scte35_action": lambda **kw: create_scte35_action(**kw),
    "create_pause_action": lambda **kw: create_pause_action(**kw),
    "create_unpause_action": lambda **kw: create_unpause_action(**kw),
    "delete_schedule_action": lambda **kw: delete_schedule_action(**kw),
    "create_immediate_input_switch": lambda **kw: create_immediate_input_switch(**kw),
    # Thumbnail (alternate name)
    "describe_thumbnail": lambda **kw: describe_channel_thumbnail(**kw),
    # Monitoring coordinator
    "get_all_metrics": lambda **kw: _monitoring_coordinator.get_all_metrics(**kw),
    "get_category_metrics": lambda **kw: _monitoring_coordinator.get_category_metrics(**kw),
    "check_channel_issues": lambda **kw: _monitoring_coordinator.check_channel_issues(**kw),
    "get_metrics_table": lambda **kw: _monitoring_coordinator.get_metrics_table(**kw),
    # No-op command for chart generation — agent already has data, just needs script execution
    "generate_chart": lambda **kw: {"status": "ready", "message": "Use DATA to generate CHART_JSON output"},
    "generate_charts": lambda **kw: {"status": "ready", "message": "Use DATA to generate CHART_JSON output"},
}

# ---------------------------------------------------------------------------
# Session Pool — pre-warmed Code Interpreter sessions
# ---------------------------------------------------------------------------

try:
    _session_pool: SessionPool | None = SessionPool(max_size=2, ttl_seconds=300)
    logger.info("SessionPool initialized (max_size=2, ttl=300s)")
except Exception as _pool_exc:
    logger.warning("SessionPool init failed: %s — falling back to per-request sessions", _pool_exc)
    _session_pool = None

_code_executor = CodeInterpreterExecutor(timeout=30, pool=_session_pool)


def _execute_local(data_json: str, script: str) -> tuple[bool, str, str]:
    """Execute a processing script locally for small responses."""
    namespace = {"DATA": data_json, "json": json, "__builtins__": __builtins__}
    stdout_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buf):
            exec(script, namespace)  # noqa: S102
        return True, stdout_buf.getvalue(), ""
    except Exception as exc:
        return False, stdout_buf.getvalue(), f"{type(exc).__name__}: {exc}"


@tool
def code_mode(command: str, code: str, args: dict = None, language: str = "python") -> dict:
    """Execute a processing script against raw API data in a sandboxed runtime.

    ONLY use when you need to filter, aggregate, or compute over a large response.
    Do NOT use for simple data retrieval — use the direct tools instead.
    For chart generation, use command="generate_chart" — this is a no-op data source
    that lets you run a script to produce CHART_JSON output without re-fetching data.

    Args:
        command: EML command (e.g. "list_channels", "get_channel_metrics", "generate_chart").
        code: Python script. DATA contains the JSON string. Use json.loads(DATA).
        args: Optional arguments for the command.
        language: Only "python" supported.
    """
    if command not in TOOL_DISPATCH_MAP:
        return {"error": f"Unknown command: '{command}'", "details": {"valid_commands": sorted(TOOL_DISPATCH_MAP.keys())}}
    if language != "python":
        return {"error": f"Unsupported language: '{language}'."}

    try:
        raw_response = TOOL_DISPATCH_MAP[command](**(args or {}))
    except Exception as exc:
        return {"error": "API call failed", "details": {"command": command, "api_error": str(exc)}}

    if isinstance(raw_response, dict) and "error" in raw_response:
        return {"error": "API call failed", "details": {"command": command, "api_error": raw_response["error"]}}

    data_json = json.dumps(raw_response, default=str)
    before_bytes = len(data_json.encode("utf-8"))

    # Smart routing: local exec for small responses, Code Interpreter for large
    if before_bytes < SMALL_RESPONSE_THRESHOLD:
        success, stdout, err_msg = _execute_local(data_json, code)
        mode_label = "code-mode-local"
    else:
        result = _code_executor.execute(data_json, code)
        success = result.success
        stdout = result.stdout or ""
        err_msg = f"{result.error_type}: {result.error_message}" if not success else ""
        mode_label = "code-mode"

    after_bytes = len(stdout.encode("utf-8")) if stdout else 0
    before_kb = before_bytes / 1024
    after_kb = after_bytes / 1024
    reduction_pct = ((before_bytes - after_bytes) / before_bytes * 100) if before_bytes > 0 else 0.0
    size_line = f"[{mode_label}: {before_kb:.1f}KB -> {after_kb:.1f}KB ({reduction_pct:.1f}% reduction)]"

    if not success:
        return {"error": err_msg, "details": {"script": code, "suggestion": "Fix the error and retry."}}
    if not stdout:
        return {"result": f"{size_line}\nWarning: no output. Use print()."}
    return {"result": f"{stdout}\n{size_line}"}


# ---------------------------------------------------------------------------
# System Prompt — DIRECT tools first. code_mode is opt-in ONLY.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an EML MediaLive assistant.

IMPORTANT — Tool usage rules:
- ALWAYS call the direct tools for data retrieval. NEVER route simple queries through code_mode.
- channel_management: action = list | describe | start | stop | thumbnail
- channel_monitoring: action = metrics | logs
- schedule_management: action = describe | input_switch | immediate_switch | scte35 | pause | unpause | delete
- channel_health_monitoring: action = all_metrics | category_metrics | check_issues | metrics_table (category param for category_metrics)
- code_mode: ONLY when the user explicitly asks to filter, aggregate, or compute over data. Never for simple retrieval.
  Also use code_mode to generate Chart.js chart specs when data benefits from visualization.
  For charts: use a SINGLE code_mode call with the data command and a script that processes DATA and prints CHART_JSON.
  The raw data stays server-side — only the script output enters the stream.
  NEVER call channel_monitoring directly before code_mode for charts.
  Output chart JSON with CHART_JSON: prefix. For chart-only generation use command="generate_chart".
  See agent instructions for the all-in-one template.
- Be concise. No tools for greetings or general questions."""

# Load behavioral instructions from prompts/agent_instructions.md
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_INSTRUCTIONS_FILE = _PROMPTS_DIR / "agent_instructions.md"
if _INSTRUCTIONS_FILE.exists():
    SYSTEM_PROMPT += "\n\n" + _INSTRUCTIONS_FILE.read_text(encoding="utf-8")
    logger.info("Loaded agent instructions from %s", _INSTRUCTIONS_FILE)
else:
    logger.warning("No agent instructions found at %s", _INSTRUCTIONS_FILE)

# 6 tools total (was 15 = ~67% schema token reduction + monitoring)
ALL_TOOLS = [
    current_time,
    channel_management,
    channel_monitoring,
    schedule_management,
    code_mode,
    channel_health_monitoring,
]

# ---------------------------------------------------------------------------
# Agent factory + FastAPI endpoints (preserved from original)
# ---------------------------------------------------------------------------

def create_agent():
    """Create MediaLive monitoring agent"""
    return Agent(
        model=BedrockModel(
            model_id=os.getenv("AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
            region_name=os.getenv("AWS_REGION", "us-west-2"),
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
    )


# Global agent instance
agent = create_agent()


@app.post("/invocations")
def invoke_agent(payload: Dict[str, Any]):
    """Invoke the MediaLive agent"""
    prompt = payload.get("input", {}).get("prompt", "Hello!")
    result = agent(prompt)
    return {"response": str(result)}


@app.post("/invocations-stream")
def invoke_agent_stream(payload: Dict[str, Any]):
    """Invoke the MediaLive agent with streaming response"""
    prompt = payload.get("input", {}).get("prompt", "Hello!")
    result = agent(prompt)
    return {"response": str(result)}


if __name__ == "__main__":
    import uvicorn

    print(f"\nSTARTING EML MEDIALIVE AGENT")
    print("-" * 40)
    print(f"Host: 0.0.0.0 | Port: {PORT} | Tools: {len(ALL_TOOLS)}")
    print("-" * 40)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
