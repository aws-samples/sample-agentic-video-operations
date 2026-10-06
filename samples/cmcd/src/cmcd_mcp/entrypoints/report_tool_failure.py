"""Expose classified tool failures through FastMCP without losing recovery guidance."""

from collections.abc import Callable
from functools import wraps

from fastmcp.exceptions import ToolError

from media_ops_contracts.tool_failure import ToolFailure


def report_tool_failure[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Convert one internal ToolFailure into a client-visible MCP error."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except ToolFailure as failure:
            message = f"{failure.kind.value}: {failure.message} Next action: {failure.next_action}"
            raise ToolError(message) from failure

    return wrapped
