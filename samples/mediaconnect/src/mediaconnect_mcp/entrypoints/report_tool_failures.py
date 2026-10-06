"""Turn classified failures into MCP errors that retain the recovery action."""

import functools
from collections.abc import Callable
from typing import Any

from fastmcp.exceptions import ToolError

from media_ops_contracts.tool_failure import ToolFailure


def report_tool_failures(tool: Callable[..., Any]) -> Callable[..., Any]:
    """Expose a safe failure kind, message, and next action to the MCP client."""

    @functools.wraps(tool)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return tool(*args, **kwargs)
        except ToolFailure as failure:
            raise ToolError(f"{failure.kind}: {failure.message} {failure.next_action}") from failure

    return wrapper
