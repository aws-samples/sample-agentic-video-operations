"""
Agent Orchestrator - Main Application

This orchestrator routes user requests to specialized subagents based on the task type.
It manages conversation context via AgentCore Memory and provides streaming responses.

Available Subagents:
- hydrolix_agent: Analyzes time-series data using Hydrolix (general queries)
- qoe_analysis_agent: Quality of Experience analysis (buffer, bitrate, session quality)
- cache_origin_agent: Cache efficiency and origin server performance analysis
"""

import logging
import json
import os
from uuid import uuid4

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands_tools import current_time, calculator
from strands.models import BedrockModel

from src.tools import hydrolix_agent, qoe_analysis_agent, cache_origin_agent
from src.utils import (
    load_file_content,
    get_agentcore_memory_messages,
    MemoryHookProvider,
    get_request_context,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator-agent")

# Environment configuration
memory_id = os.environ.get("MEMORY_ID")
bedrock_model_id = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
)

# Initialize the Bedrock Agent Core app
app = BedrockAgentCoreApp()


def load_orchestrator_prompt():
    """Load the orchestrator system prompt."""
    fallback_prompt = """You are an intelligent assistant orchestrator. Your role is to understand user requests 
and route them to the appropriate specialized subagent. You have access to:

- video_games_sales_agent: For analyzing video game sales data, market trends, and business insights
- hydrolix_agent: For general time-series data queries and combined analysis
- qoe_analysis_agent: For Quality of Experience analysis (buffer health, bitrate, session quality, rebuffering)
- cache_origin_agent: For cache efficiency, origin performance, error rates, and bandwidth analysis

Always use the appropriate subagent tool to handle user requests. Provide helpful, conversational responses."""

    try:
        prompt = load_file_content("orchestrator_instructions.txt", default_content=fallback_prompt)
        return prompt
    except Exception:
        return fallback_prompt


ORCHESTRATOR_SYSTEM_PROMPT = load_orchestrator_prompt()


@app.entrypoint
async def agent_invocation(payload):
    """
    Main entry point for the orchestrator agent with streaming responses.

    Expected payload structure:
    {
        "prompt": "User question or request",
        "prompt_uuid": "optional-unique-identifier",
        "user_timezone": "US/Pacific",
        "session_id": "optional-session-id",
        "user_id": "optional-user-id",
        "last_k_turns": "optional-context-turns"
    }

    Returns:
        AsyncGenerator: Yields streaming response chunks
    """
    try:
        # Extract parameters
        user_message = payload.get(
            "prompt",
            "No prompt found. Please provide a 'prompt' key in your request.",
        )
        prompt_uuid = payload.get("prompt_uuid", str(uuid4()))
        user_timezone = payload.get("user_timezone", "US/Pacific")
        session_id = payload.get("session_id", str(uuid4()))
        user_id = payload.get("user_id", "guest")
        last_k_turns = int(payload.get("last_k_turns", 20))

        print(f"\n{'='*80}")
        print("🎯 ORCHESTRATOR REQUEST")
        print(f"{'='*80}")
        print(f"💬 Query: {user_message[:100]}{'...' if len(user_message) > 100 else ''}")
        print(f"🤖 Model: {bedrock_model_id}")
        print(f"🆔 Prompt UUID: {prompt_uuid}")
        print(f"🔗 Session: {session_id}")
        print(f"👤 User: {user_id}")
        print(f"{'='*80}")

        # Set request context for subagents
        ctx = get_request_context()
        ctx.set(
            prompt_uuid=prompt_uuid,
            user_timezone=user_timezone,
            session_id=session_id,
            user_id=user_id
        )

        # Initialize model
        bedrock_model = BedrockModel(model_id=bedrock_model_id)

        # Load conversation context
        agentcore_messages = get_agentcore_memory_messages(
            memory_id, user_id, session_id, last_k_turns
        )

        print(f"📋 Loaded {len(agentcore_messages)} context messages")

        # Configure system prompt with timezone
        system_prompt = ORCHESTRATOR_SYSTEM_PROMPT.replace("{timezone}", user_timezone)

        # Create orchestrator agent with subagent tools
        agent = Agent(
            messages=agentcore_messages,
            model=bedrock_model,
            system_prompt=system_prompt,
            hooks=[MemoryHookProvider(memory_id, user_id, session_id, last_k_turns)],
            tools=[
                hydrolix_agent,
                qoe_analysis_agent,
                cache_origin_agent,
                current_time,
                calculator,
            ],
            callback_handler=None,
        )

        print("🚀 Processing request...")
        print(f"{'='*80}")

        # Stream the response
        tool_active = False

        async for item in agent.stream_async(user_message):
            if "event" in item:
                event = item["event"]

                if "contentBlockStart" in event and "toolUse" in event[
                    "contentBlockStart"
                ].get("start", {}):
                    tool_active = True
                    yield json.dumps({"event": event}) + "\n"

                elif "contentBlockStop" in event and tool_active:
                    tool_active = False
                    yield json.dumps({"event": event}) + "\n"

            elif "start_event_loop" in item:
                yield json.dumps(item) + "\n"
            elif "current_tool_use" in item and tool_active:
                yield json.dumps(item["current_tool_use"]) + "\n"
            elif "data" in item:
                yield json.dumps({"data": item["data"]}) + "\n"

    except Exception as e:
        import traceback
        tb = traceback.extract_tb(e.__traceback__)
        filename, line_number, function_name, text = tb[-1]
        error_msg = f"Error: {str(e)} (Line {line_number} in {filename})"
        print(f"\n❌ ORCHESTRATOR ERROR: {error_msg}")
        yield f"I encountered an error processing your request: {error_msg}"


if __name__ == "__main__":
    print(f"\n{'='*80}")
    print("🚀 STARTING AGENT ORCHESTRATOR")
    print(f"{'='*80}")
    print("📡 Server: port 8080")
    print("🌐 Health: /ping")
    print("🎯 Invoke: /invocations")
    print(f"{'='*80}")
    app.run()
