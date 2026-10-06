"""
Agent Orchestrator - Main Application

This orchestrator routes user requests to specialized subagents based on the task type.
It manages conversation context via AgentCore Memory and provides streaming responses.

Available Subagents:
- hydrolix_agent: Analyzes time-series data using Hydrolix (general queries)
- qoe_analysis_agent: Quality of Experience analysis (buffer, bitrate, session quality)
- cache_origin_agent: Cache efficiency and origin server performance analysis
"""

import asyncio
import json
import logging
from uuid import uuid4

from bedrock_agentcore import BedrockAgentCoreApp
from src.settings.runtime_settings import load_runtime_settings
from src.tools import cache_origin_agent, hydrolix_agent, qoe_analysis_agent
from src.utils import (
    MemoryHookProvider,
    get_agentcore_memory_messages,
    load_file_content,
    set_request_context,
)
from src.utils.identify_caller import CallerRefused, identify_caller
from src.utils.request_context import REQUEST_TIMEOUT_SECONDS
from src.utils.resolve_user_timezone import DEFAULT_TIMEZONE, resolve_user_timezone
from strands import Agent
from strands.hooks import HookCallback, HookProvider
from strands.models import BedrockModel
from strands.types.content import Message
from strands_tools import calculator, current_time

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator-agent")

# Environment configuration
runtime_settings = load_runtime_settings()
bedrock_model_id = runtime_settings.agent_model_id
memory_id = runtime_settings.memory_id

# Initialize the Bedrock Agent Core app
app = BedrockAgentCoreApp()


def load_orchestrator_prompt():
    """Load the orchestrator system prompt."""
    fallback_prompt = (
        "You are Gus, a Hydrolix CDN analytics orchestrator. Route each request "
        "to one available specialist:\n\n"
        "- hydrolix_agent: general time-series and combined analysis\n"
        "- qoe_analysis_agent: viewer experience, buffer, bitrate, and sessions\n"
        "- cache_origin_agent: cache efficiency, origin performance, and errors\n\n"
        "Use the best specialist and return a clear, conversational response."
    )

    try:
        prompt = load_file_content("orchestrator_instructions.txt", default_content=fallback_prompt)
        return prompt
    except Exception:
        return fallback_prompt


ORCHESTRATOR_SYSTEM_PROMPT = load_orchestrator_prompt()


MEMORY_OFF_NOTICE = (
    "Memory is off: this runtime has no verified caller identity (IAM mode), so no "
    "conversation history is read or kept. Deploy with HYDROLIX_JWT_DISCOVERY_URL and "
    "HYDROLIX_JWT_CLIENT_IDS to bind each user's memory to their sign-in."
)


STOPPED_AT_DEADLINE = (
    f"The assistant stopped: this request reached its {REQUEST_TIMEOUT_SECONDS}-second limit. "
    "Ask a narrower question, for example a shorter time range."
)


@app.entrypoint
async def agent_invocation(payload, context):
    """
    Main entry point for the orchestrator agent with streaming responses.

    Expected payload structure:
    {
        "prompt": "User question or request",
        "prompt_uuid": "optional-unique-identifier",
        "user_timezone": "US/Pacific",
        "last_k_turns": "optional-context-turns"
    }

    The caller and the conversation come from the request, not the payload: the verified
    token's `sub` and the AgentCore runtime session id (src/utils/identify_caller.py).

    Returns:
        AsyncGenerator: Yields streaming response chunks
    """
    try:
        caller = identify_caller(
            getattr(context, "session_id", None),
            getattr(context, "request_headers", None),
            runtime_settings,
        )
    except CallerRefused as refusal:
        print(f"⛔ Request refused: {refusal}")
        yield json.dumps({"error": str(refusal)}) + "\n"
        return

    try:
        user_message = payload.get(
            "prompt",
            "No prompt found. Please provide a 'prompt' key in your request.",
        )
        prompt_uuid = payload.get("prompt_uuid", str(uuid4()))
        # It goes into the system prompts: a real zone name, or UTC.
        user_timezone = resolve_user_timezone(payload.get("user_timezone", DEFAULT_TIMEZONE))
        last_k_turns = int(payload.get("last_k_turns", 20))

        # Metadata only (RB10): no prompt text, no user or session id.
        mode = "memory on" if caller.memory_enabled else "memory off"
        print(f"🎯 Orchestrator request (prompt length={len(user_message)}, {mode})")

        # This request's context for its subagents, with its own tool-call budget.
        request = set_request_context(prompt_uuid=prompt_uuid, user_timezone=user_timezone)

        bedrock_model = BedrockModel(model_id=bedrock_model_id)

        agentcore_messages: list[Message] = []
        hooks: list[HookProvider | HookCallback] = []
        if caller.actor_id is not None:
            agentcore_messages = get_agentcore_memory_messages(
                memory_id, caller.actor_id, caller.session_id, last_k_turns
            )
            hooks = [
                MemoryHookProvider(memory_id, caller.actor_id, caller.session_id, last_k_turns)
            ]
        else:
            yield json.dumps({"notice": MEMORY_OFF_NOTICE}) + "\n"

        system_prompt = ORCHESTRATOR_SYSTEM_PROMPT.replace("{timezone}", user_timezone)

        agent = Agent(
            messages=agentcore_messages,
            model=bedrock_model,
            system_prompt=system_prompt,
            hooks=[*hooks, request.tool_budget],
            tools=[
                hydrolix_agent,
                qoe_analysis_agent,
                cache_origin_agent,
                current_time,
                calculator,
            ],
            callback_handler=None,
        )

        # Stream the response
        tool_active = False

        # The request's deadline bounds the orchestrator too: each wait for its next event
        # gets only the time left, so a late answer is never streamed.
        stream = agent.stream_async(user_message)
        while True:
            seconds_left = request.tool_budget.seconds_left()
            if seconds_left <= 0:
                raise TimeoutError
            try:
                item = await asyncio.wait_for(anext(stream), seconds_left)
            except StopAsyncIteration:
                break
            if "event" in item:
                event = item["event"]

                if "contentBlockStart" in event and "toolUse" in event["contentBlockStart"].get(
                    "start", {}
                ):
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

    except TimeoutError:
        logger.warning("Orchestrator request stopped at the request deadline")
        yield json.dumps({"error": STOPPED_AT_DEADLINE}) + "\n"
    except Exception as e:
        # The class name only: an exception message can quote the question or the data.
        logger.error("Orchestrator request failed: %s", type(e).__name__)
        yield json.dumps({"error": "The assistant could not finish this request. Retry."}) + "\n"


if __name__ == "__main__":
    print(f"\n{'=' * 80}")
    print("🚀 STARTING AGENT ORCHESTRATOR")
    print(f"{'=' * 80}")
    print("📡 Server: port 8080")
    print("🌐 Health: /ping")
    print("🎯 Invoke: /invocations")
    print(f"{'=' * 80}")
    app.run()
