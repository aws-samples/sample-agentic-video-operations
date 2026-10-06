"""Turn a classified ToolFailure into an MCP tool error (write_safe_tools.md §2)."""

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastmcp.exceptions import ToolError

from media_ops_contracts.tool_failure import ToolFailure


def report_tool_failures(tool: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(tool):

        @functools.wraps(tool)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await tool(*args, **kwargs)
            except ToolFailure as failure:
                raise as_tool_error(failure) from failure

        return async_wrapper

    @functools.wraps(tool)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return tool(*args, **kwargs)
        except ToolFailure as failure:
            raise as_tool_error(failure) from failure

    return wrapper


def as_tool_error(failure: ToolFailure) -> ToolError:
    return ToolError(f"{failure.kind}: {failure.message} {failure.next_action}")
