"""
Stream Processing Utilities for Agent Responses

This module provides utilities for processing streaming responses from Strands agents,
handling tool use events, and collecting text output.
"""

import json

from strands import Agent

from src.settings.runtime_settings import load_runtime_settings

from .check_hydrolix_query import QueryRefused, check_select_query
from .request_context import get_request_context
from .utils import save_raw_query_result


def _would_run(sql_query: str) -> bool:
    """The model has written the call; save it only if the hooks will let it run."""
    budget = get_request_context().tool_budget
    if budget.calls >= budget.limit or budget.seconds_left() <= 0:
        return False
    try:
        check_select_query(sql_query, load_runtime_settings().hydrolix_table)
    except QueryRefused:
        return False
    return True


async def process_agent_stream(agent: Agent, query: str, agent_name: str | None = None) -> str:
    """
    Process the agent stream and collect the response.

    This function handles streaming responses from a Strands agent, processing
    tool use events and collecting text output. Logs carry metadata only (tool names,
    counts and lengths), never the question, the SQL or the answer (RB10).

    When the run_select_query tool completes, its query is saved to DynamoDB for the
    browser to show, unless the runtime refuses it (it then never ran).

    Args:
        agent: The Strands Agent instance to stream from
        query: The query string to send to the agent
        agent_name: Optional name of the agent executing the query (for tracking)

    Returns:
        str: The collected text response from the agent stream
    """
    collected_text = []
    tool_active = False
    current_tool_info = {}

    # Get request context for UUID
    ctx = get_request_context()
    prompt_uuid = ctx.prompt_uuid

    async for item in agent.stream_async(query):
        if "event" in item:
            event = item["event"]

            if "contentBlockStart" in event and "toolUse" in event["contentBlockStart"].get(
                "start", {}
            ):
                tool_active = True
                tool_use = event["contentBlockStart"]["start"]["toolUse"]
                # Initialize tracking for this tool use
                current_tool_info = {
                    "toolUseId": tool_use.get("toolUseId"),
                    "name": tool_use.get("name"),
                    "input": "",
                }
                print(f"🔧 Tool started: {tool_use.get('name')} (agent={agent_name})")

            elif "contentBlockStop" in event and tool_active:
                tool_active = False

                # When tool completes, check if it's run_select_query and print complete info
                if current_tool_info.get("name") == "run_select_query" and current_tool_info.get(
                    "input"
                ):
                    try:
                        # Parse the accumulated input JSON string
                        input_dict = json.loads(current_tool_info["input"])
                        complete_tool_info = {
                            "toolUseId": current_tool_info["toolUseId"],
                            "name": current_tool_info["name"],
                            "input": input_dict,
                        }

                        sql_query = complete_tool_info["input"].get("query", "")

                        print(
                            f"🔍 run_select_query completed (agent={agent_name}, "
                            f"query length={len(sql_query)})"
                        )

                        # Save query to DynamoDB
                        if prompt_uuid and sql_query and _would_run(sql_query):
                            save_raw_query_result(
                                user_prompt_uuid=prompt_uuid,
                                user_prompt=query,
                                sql_query=sql_query,
                                sql_query_description=f"Query executed by {agent_name or 'agent'}",
                                result={"toolUseId": complete_tool_info["toolUseId"]},
                                message="Query captured from stream",
                                agent_name=agent_name,
                            )

                    except json.JSONDecodeError:
                        length = len(current_tool_info["input"])
                        print(f"⚠️ Could not parse run_select_query input (length={length})")

                # Reset tool info
                current_tool_info = {}

        elif "current_tool_use" in item and tool_active:
            tool_use_data = item["current_tool_use"]

            # Accumulate the input string as it streams in
            if "input" in tool_use_data and current_tool_info.get("name") == "run_select_query":
                current_tool_info["input"] = tool_use_data["input"]

        elif "data" in item:
            collected_text.append(item["data"])

    response = "".join(collected_text)
    print(f"✅ Subagent {agent_name} answered (length={len(response)})")
    return response
