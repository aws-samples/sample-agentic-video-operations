"""Read-only composite tools for the MediaLive Strands agent (fewer tool schemas per call).

No write tool is registered here: this agent has no approval path (write_safe_tools.md §3).
`code_mode` exists only with ENABLE_CODE_MODE=true.
"""

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from strands import tool

from media_ops_contracts.tool_failure import ToolFailure
from medialive_mcp.adapters.cloudwatch_logs.read_channel_logs import read_channel_logs
from medialive_mcp.adapters.media_live.describe_channel import describe_channel
from medialive_mcp.adapters.media_live.describe_schedule import describe_schedule
from medialive_mcp.adapters.media_live.list_channels import list_channels
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.domain.resolve_channel_id import resolve_channel_id
from medialive_mcp.settings.runtime_settings import RuntimeSettings
from medialive_mcp.strands_agent.run_processing_script import run_processing_script
from medialive_mcp.workflows.check_channel_health import (
    build_metrics_table,
    check_channel_issues,
    recent_window,
    summarize_channel_metrics,
)
from medialive_mcp.workflows.describe_channel_thumbnail import describe_channel_thumbnail


def to_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, list):
        return json.dumps([item.model_dump(mode="json") for item in value])
    return json.dumps(value, default=str)


def answer(read: Callable[[], Any]) -> str:
    try:
        return to_json(read())
    except ToolFailure as failure:
        return json.dumps(
            {"error": failure.kind, "message": failure.message, "next_action": failure.next_action}
        )


def choose(action: str, dispatch: dict[str, Callable[[], Any]]) -> str:
    if action not in dispatch:
        return json.dumps({"error": f"Unknown action '{action}'", "valid_actions": list(dispatch)})
    return answer(dispatch[action])


def create_composite_tools(settings: RuntimeSettings, clients: MediaLiveClients) -> list:
    def channel(channel_id: str | None) -> str:
        return resolve_channel_id(channel_id, settings.medialive_channel_id)

    reads: dict[str, Callable[..., Any]] = {
        "list_channels": lambda **_: list_channels(clients.medialive),
        "describe_channel": lambda channel_id=None, **_: describe_channel(
            clients.medialive, channel(channel_id)
        ),
        "get_channel_metrics": lambda channel_id=None, hours_back=1, category=None, **_: (
            summarize_channel_metrics(clients, channel(channel_id), hours_back, category)
        ),
        "get_channel_logs": lambda channel_id=None, hours_back=1, **_: read_channel_logs(
            clients.logs, channel(channel_id), recent_window(hours_back)
        ),
        "check_channel_issues": lambda channel_id=None, hours_back=24, **_: check_channel_issues(
            clients, channel(channel_id), hours_back
        ),
        "get_metrics_table": lambda channel_id=None, hours_back=6, **_: build_metrics_table(
            clients, channel(channel_id), hours_back
        ),
        "describe_schedule": lambda channel_id=None, **_: describe_schedule(
            clients.medialive, channel(channel_id)
        ),
    }

    @tool
    def channel_management(action: str, channel_id: str = None, pipeline_id: str = "0") -> str:
        """Read MediaLive channels. action: list | describe | thumbnail."""
        return choose(
            action,
            {
                "list": lambda: reads["list_channels"](),
                "describe": lambda: reads["describe_channel"](channel_id=channel_id),
                "thumbnail": lambda: describe_channel_thumbnail(
                    clients, channel(channel_id), pipeline_id, settings.thumbnail_model_id
                ),
            },
        )

    @tool
    def channel_monitoring(action: str, channel_id: str = None, hours_back: int = 1) -> str:
        """Channel metrics or recent logs. action: metrics | logs."""
        return choose(
            action,
            {
                "metrics": lambda: reads["get_channel_metrics"](channel_id, hours_back),
                "logs": lambda: reads["get_channel_logs"](channel_id, hours_back),
            },
        )

    @tool
    def schedule_management(action: str, channel_id: str = None) -> str:
        """Read the channel schedule. action: describe."""
        return choose(action, {"describe": lambda: reads["describe_schedule"](channel_id)})

    @tool
    def channel_health_monitoring(
        action: str, channel_id: str = None, hours_back: int = 1, category: str = ""
    ) -> str:
        """Five-category health. action: all_metrics | category_metrics | check_issues |
        metrics_table. category (for category_metrics): channel_health, input_health,
        output_health, media_health, content_quality."""
        return choose(
            action,
            {
                "all_metrics": lambda: reads["check_channel_issues"](channel_id, hours_back),
                "category_metrics": lambda: reads["get_channel_metrics"](
                    channel_id, hours_back, category or None
                ),
                "check_issues": lambda: reads["check_channel_issues"](channel_id, hours_back),
                "metrics_table": lambda: reads["get_metrics_table"](channel_id, hours_back),
            },
        )

    tools = [channel_management, channel_monitoring, schedule_management, channel_health_monitoring]
    if settings.enable_code_mode:
        tools.append(create_code_mode_tool(reads))
    return tools


def create_code_mode_tool(reads: dict[str, Callable[..., Any]]):
    from medialive_mcp.code_interpreter import CodeInterpreterExecutor

    executor = CodeInterpreterExecutor(timeout=30)

    @tool
    def code_mode(command: str, code: str, args: dict = None) -> dict:
        """Run a Python script over one read command's data. DATA holds the JSON string.
        Use only to filter, aggregate or chart large data. Print the result."""
        if command not in reads:
            return {"error": f"Unknown command '{command}'", "valid_commands": sorted(reads)}
        try:
            data_json = to_json(reads[command](**(args or {})))
        except ToolFailure as failure:
            return {"error": failure.kind, "message": failure.message}
        succeeded, stdout, error = run_processing_script(data_json, code, executor)
        if not succeeded:
            return {"error": error, "suggestion": "Fix the script and retry."}
        return {"result": stdout or "No output. Use print()."}

    return code_mode
