"""
Stream Processing Utilities for Agent Responses

This module provides utilities for processing streaming responses from Strands agents,
handling tool use events, and collecting text output.
"""

import json

from strands import Agent


async def process_agent_stream(agent: Agent, query: str, agent_name: str | None = None) -> str:
    """
    Process the agent stream and collect the response.

    This function handles streaming responses from a Strands agent, processing
    tool use events and collecting text output. Logs carry metadata only (tool names,
    counts and lengths), never the question, the SQL or the answer.

    The queries themselves are recorded after they run, with their status, by
    RecordExecutedQueries, not here when the model writes them.

    Args:
        agent: The Strands Agent instance to stream from
        query: The query string to send to the agent
        agent_name: Optional name of the agent executing the query (for tracking)

    Returns:
        str: The collected text response from the agent stream
    """
    collected_text = []
    tool_active = False
    current_tool_info: dict[str, str] = {}

    async for item in agent.stream_async(query):
        if "event" in item:
            event = item["event"]

            if "contentBlockStart" in event and "toolUse" in event["contentBlockStart"].get(
                "start", {}
            ):
                tool_active = True
                tool_use = event["contentBlockStart"]["start"]["toolUse"]
                current_tool_info = {"name": tool_use.get("name", ""), "input": ""}
                print(f"🔧 Tool started: {tool_use.get('name')} (agent={agent_name})")

            elif "contentBlockStop" in event and tool_active:
                tool_active = False
                if current_tool_info.get("name") == "run_select_query" and current_tool_info.get(
                    "input"
                ):
                    try:
                        sql_query = json.loads(current_tool_info["input"]).get("query", "")
                        print(
                            f"🔍 run_select_query written (agent={agent_name}, "
                            f"query length={len(sql_query)})"
                        )
                    except json.JSONDecodeError:
                        length = len(current_tool_info["input"])
                        print(f"⚠️ Could not parse run_select_query input (length={length})")
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
