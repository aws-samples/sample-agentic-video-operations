"""
Stream Processing Utilities for Agent Responses

This module provides utilities for processing streaming responses from Strands agents,
handling tool use events, and collecting text output.
"""

import json
from strands import Agent
from .utils import save_raw_query_result
from .request_context import get_request_context


async def process_agent_stream(agent: Agent, query: str, agent_name: str = None) -> str:
    """
    Process the agent stream and collect the response.
    
    This function handles streaming responses from a Strands agent, processing
    tool use events and collecting text output. It prints events and tool usage
    information to stdout for monitoring and debugging.
    
    When the run_select_query tool completes, it captures and prints the complete
    tool use information including toolUseId, name, and full input parameters.
    The query is also saved to DynamoDB for audit trail.
    
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

            if "contentBlockStart" in event and "toolUse" in event[
                "contentBlockStart"
            ].get("start", {}):
                tool_active = True
                tool_use = event["contentBlockStart"]["start"]["toolUse"]
                # Initialize tracking for this tool use
                current_tool_info = {
                    "toolUseId": tool_use.get("toolUseId"),
                    "name": tool_use.get("name"),
                    "input": ""
                }
                print(json.dumps({"event": event}))

            elif "contentBlockStop" in event and tool_active:
                tool_active = False
                
                # When tool completes, check if it's run_select_query and print complete info
                if current_tool_info.get("name") == "run_select_query" and current_tool_info.get("input"):
                    try:
                        # Parse the accumulated input JSON string
                        input_dict = json.loads(current_tool_info["input"])
                        complete_tool_info = {
                            "toolUseId": current_tool_info["toolUseId"],
                            "name": current_tool_info["name"],
                            "input": input_dict
                        }
                        
                        sql_query = complete_tool_info['input'].get('query', '')
                        
                        print(f"\n{'='*60}")
                        print("🔍 COMPLETED TOOL USE: run_select_query")
                        print(f"{'='*60}")
                        print(f"Tool Use ID: {complete_tool_info['toolUseId']}")
                        print(f"Tool Name: {complete_tool_info['name']}")
                        print(f"Query: {sql_query}")
                        if agent_name:
                            print(f"Agent: {agent_name}")
                        print(f"{'='*60}\n")
                        
                        # Save query to DynamoDB
                        if prompt_uuid and sql_query:
                            save_raw_query_result(
                                user_prompt_uuid=prompt_uuid,
                                user_prompt=query,
                                sql_query=sql_query,
                                sql_query_description=f"Query executed by {agent_name or 'agent'}",
                                result={"toolUseId": complete_tool_info['toolUseId']},
                                message="Query captured from stream",
                                agent_name=agent_name
                            )
                            
                    except json.JSONDecodeError:
                        print(f"\n⚠️ Warning: Could not parse tool input JSON: {current_tool_info['input']}\n")
                
                # Reset tool info
                current_tool_info = {}
                print(json.dumps({"event": event}))

        elif "start_event_loop" in item:
            print(json.dumps(item))
        elif "current_tool_use" in item and tool_active:
            tool_use_data = item["current_tool_use"]
            print(json.dumps(tool_use_data))
            
            # Accumulate the input string as it streams in
            if "input" in tool_use_data and current_tool_info.get("name") == "run_select_query":
                current_tool_info["input"] = tool_use_data["input"]
                
        elif "data" in item:
            collected_text.append(item["data"])
            print(item["data"], end="", flush=True)
    
    print()  # New line after streaming
    return "".join(collected_text)
