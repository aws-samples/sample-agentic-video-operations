"""AgentCore Runtime entrypoint of the read-only MediaLive Strands agent."""

from typing import Any

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.prompts.medialive_agent_prompt import MEDIALIVE_AGENT_PROMPT
from medialive_mcp.settings.runtime_settings import RuntimeSettings, load_runtime_settings
from medialive_mcp.strands_agent.create_composite_tools import create_composite_tools

ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"

app = BedrockAgentCoreApp()
_settings = load_runtime_settings()
_tools = create_composite_tools(_settings, create_medialive_clients(_settings))
_agent: Agent | None = None  # the runtime container is pinned to one session


def create_agent(settings: RuntimeSettings, actor_id: str, session_id: str) -> Agent:
    if not settings.agent_model_id:
        raise RuntimeError("AGENT_MODEL_ID is not set. Set it in the root .env or the CDK stack.")
    session_manager = None
    if settings.memory_id:
        config = AgentCoreMemoryConfig(
            memory_id=settings.memory_id,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config={
                f"/medialive/{actor_id}/channels": RetrievalConfig(top_k=5, relevance_score=0.5),
                f"/medialive/{actor_id}/issues": RetrievalConfig(top_k=3, relevance_score=0.6),
            },
        )
        session_manager = AgentCoreMemorySessionManager(config, settings.aws_region)
    return Agent(
        model=settings.agent_model_id,
        session_manager=session_manager,
        system_prompt=MEDIALIVE_AGENT_PROMPT,
        tools=_tools,
    )


@app.entrypoint
async def invoke(payload: dict[str, Any], context: Any):
    global _agent
    headers = context.request_headers or {}
    actor_id = headers.get(ACTOR_HEADER, "user")
    session_id = context.session_id or "default-session"
    if _agent is None:
        _agent = create_agent(_settings, actor_id, session_id)
    prompt, stream = payload.get("prompt", ""), bool(payload.get("stream"))
    try:
        async for event in respond(_agent, prompt, stream):
            yield event
    except Exception as error:  # boundary: recover once from a stale tool history in memory
        if "toolResult blocks" not in str(error):
            raise
        _agent = create_agent(_settings, actor_id, session_id)
        async for event in respond(_agent, prompt, stream):
            yield event


async def respond(agent: Agent, prompt: str, stream: bool):
    if stream:
        async for event in agent.stream_async(prompt):
            yield event
        return
    result = agent(prompt)
    yield {"response": result.message.get("content", [{}])[0].get("text", str(result))}


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
