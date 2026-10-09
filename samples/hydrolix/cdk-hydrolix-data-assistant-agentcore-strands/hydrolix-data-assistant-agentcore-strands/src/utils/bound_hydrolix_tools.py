"""Give the subagents only the Hydrolix tools they need, each bound to HYDROLIX_TABLE."""

from collections.abc import Iterable
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.types.tools import AgentTool

from .check_hydrolix_query import QueryRefused, check_select_query, check_table_info_request

# list_databases and list_tables only invite reading other tables, so the model never sees them.
EXPOSED_MCP_TOOLS = ("run_select_query", "get_table_info")


def expose_bounded_tools(tools: Iterable[AgentTool]) -> list[AgentTool]:
    return [tool for tool in tools if tool.tool_name in EXPOSED_MCP_TOOLS]


class BoundHydrolixTools(HookProvider):
    """Cancels a call before it reaches the cluster unless it stays on the configured table."""

    def __init__(self, table: str) -> None:
        self.table = table

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check_call)

    def check_call(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        tool_input = event.tool_use.get("input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        try:
            if name == "run_select_query":
                check_select_query(str(tool_input.get("query", "")), self.table)
            elif name == "get_table_info":
                check_table_info_request(tool_input, self.table)
        except QueryRefused as refused:
            event.cancel_tool = (
                f"Refused: {refused}. Query only {self.table}, with one SELECT statement."
            )
