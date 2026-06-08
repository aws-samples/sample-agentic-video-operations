"""Coordinator AgentCore Runtime entrypoint.

Uses create_agent (same pattern as EML/EMX) with routing tools that
invoke specialist runtimes. The write_todos planning happens via
the LLM's tool-calling loop — the coordinator model decides when to
plan, route, and merge based on the system prompt.
"""

import json
from uuid import uuid4

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph_checkpoint_aws import AgentCoreMemorySaver

from shared.memory import create_checkpointer, build_config
from shared.config import Settings
from shared.runtime_client import AgentCoreRuntimeClient

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """You are a media operations coordinator managing a live streaming pipeline.
You have access to two specialist agents:
- EML (MediaLive): For encoding, channel management, monitoring, and scheduling
- EMX (MediaConnect): For transport, flow management, and routing

Your workflow:
1. Classify the user's request (which agent(s) are needed)
2. Plan the tasks (break complex requests into steps)
3. For DESTRUCTIVE operations (start, stop, switch, delete): state what you plan to do and ask for confirmation before executing
4. Execute by calling the appropriate specialist(s)
5. Merge results into a clear, unified response

For simple queries (list, describe, metrics), skip planning and route directly.
Always report which specialist provided each piece of information."""


@tool
def invoke_eml(task_description: str) -> str:
    """Invoke the EML (MediaLive) specialist agent with a specific task.
    Use for: listing channels, describing channels, metrics, logs, scheduling, start/stop.
    """
    settings = Settings()
    client = AgentCoreRuntimeClient(region=settings.region)
    session_id = f"eml-delegation-{uuid4()}"
    try:
        return client.invoke(
            runtime_arn=settings.eml_runtime_arn,
            task={"task_id": str(uuid4()), "description": task_description},
            session_id=session_id,
        )
    except Exception as e:
        return f"EML agent error: {e}"


@tool
def invoke_emx(task_description: str) -> str:
    """Invoke the EMX (MediaConnect) specialist agent with a specific task.
    Use for: listing flows, describing flows, metrics, thumbnails, start/stop.
    """
    settings = Settings()
    client = AgentCoreRuntimeClient(region=settings.region)
    session_id = f"emx-delegation-{uuid4()}"
    try:
        return client.invoke(
            runtime_arn=settings.emx_runtime_arn,
            task={"task_id": str(uuid4()), "description": task_description},
            session_id=session_id,
        )
    except Exception as e:
        return f"EMX agent error: {e}"


@tool
def write_todos(plan: str) -> str:
    """Write a task plan before executing. Use for complex multi-step requests.
    Input should be a numbered list of tasks with their target agent (EML or EMX).
    This helps track what needs to be done and in what order.
    """
    return f"Plan recorded:\n{plan}\n\nProceed with execution."


def build_coordinator(checkpointer: AgentCoreMemorySaver):
    """Build the coordinator agent."""
    settings = Settings()
    model = init_chat_model(
        settings.agent_model_id,
        model_provider="bedrock_converse",
        region_name=settings.region,
    )
    return create_agent(
        model,
        tools=[invoke_eml, invoke_emx, write_todos],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


@app.entrypoint
async def invoke(payload, context):
    """AgentCore Runtime entry point."""
    settings = Settings()
    checkpointer = create_checkpointer(settings.memory_id, settings.region)
    graph = build_coordinator(checkpointer)

    prompt = payload.get("prompt", "Hello!")
    session_id = payload.get("session_id") or context.session_id or f"session-{uuid4()}"
    user_id = (
        context.request_headers.get("X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id", "user")
        if context.request_headers
        else "user"
    )

    config = build_config("coordinator", user_id, session_id)

    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
    )

    response_text = result["messages"][-1].content
    yield json.dumps({"data": response_text}) + "\n"


if __name__ == "__main__":
    app.run()
