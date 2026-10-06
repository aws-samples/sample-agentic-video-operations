"""Turn a classified ToolFailure into an MCP tool error the client can show (tool-contract §2)."""

import functools
from collections.abc import Callable
from typing import Any

from fastmcp.exceptions import ToolError

from media_ops_contracts.tool_failure import ToolFailure


def report_tool_failures(tool: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(tool)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return tool(*args, **kwargs)
        except ToolFailure as failure:
            raise ToolError(f"{failure.kind}: {failure.message} {failure.next_action}") from failure

    return wrapper
