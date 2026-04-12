"""
EML MediaLive Agent - Production-Ready with Memory
Lazy-loaded agent with AgentCore memory integration
"""
import os
from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

# Import composite tools and system prompt from app.py
from src.app import (
    current_time, channel_management, channel_monitoring,
    schedule_management, code_mode, channel_health_monitoring, SYSTEM_PROMPT
)

app = BedrockAgentCoreApp()


def build_metrics_event(agent):
    """Build a metadata stream event from the agent's accumulated metrics."""
    try:
        m = getattr(agent, 'event_loop_metrics', None)
        if m is None:
            return None
        usage = {}
        metrics = {}
        tools = {}
        cycles = 0
        invocation = {"cycles": []}

        if hasattr(m, 'accumulated_usage'):
            usage = dict(m.accumulated_usage) if m.accumulated_usage else {}
        if hasattr(m, 'accumulated_metrics'):
            metrics = dict(m.accumulated_metrics) if m.accumulated_metrics else {}
        if hasattr(m, 'tool_metrics') and m.tool_metrics:
            for name, t in m.tool_metrics.items():
                tools[name] = {
                    "calls": getattr(t, 'call_count', 0),
                    "successes": getattr(t, 'success_count', 0),
                    "errors": getattr(t, 'error_count', 0),
                    "duration": getattr(t, 'total_time', 0),
                }
        if hasattr(m, 'cycle_count'):
            cycles = m.cycle_count
        if hasattr(m, 'latest_agent_invocation') and m.latest_agent_invocation:
            inv = m.latest_agent_invocation
            cycles = len(inv.cycles) if inv.cycles else cycles
            inv = m.latest_agent_invocation
            if hasattr(inv, 'cycles') and inv.cycles:
                invocation["cycles"] = [
                    {"cycle_id": getattr(c, 'event_loop_cycle_id', i), "usage": getattr(c, 'usage', {})}
                    for i, c in enumerate(inv.cycles)
                ]

        if not usage:
            return None

        return {
            "event": {
                "metadata": {
                    "usage": usage,
                    "metrics": metrics,
                    "tools": tools,
                    "cycles": cycles,
                    "invocation": invocation,
                }
            }
        }
    except Exception:
        return None

MEMORY_ID = os.getenv("BEDROCK_AGENTCORE_MEMORY_ID", "")
REGION = os.getenv("AWS_REGION", "us-west-2")
MODEL_ID = os.getenv("AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

# Global agent instance - survives across invocations within the same runtime
_agent = None
# Cached memory configuration
_memory_config_cache = {}

def get_memory_config(actor_id: str, session_id: str) -> AgentCoreMemoryConfig:
    """Get or create cached memory configuration"""
    cache_key = f"{actor_id}_{session_id}"
    if cache_key not in _memory_config_cache:
        _memory_config_cache[cache_key] = AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config={
                f"/medialive/{actor_id}/channels": RetrievalConfig(top_k=5, relevance_score=0.5),
                f"/medialive/{actor_id}/issues": RetrievalConfig(top_k=3, relevance_score=0.6)
            }
        )
    return _memory_config_cache[cache_key]

def get_or_create_agent(actor_id: str, session_id: str) -> Agent:
    """
    Get existing agent or create new one with memory configuration.
    Since the container is pinned to the session ID, we only need one agent per container.
    """
    global _agent
    
    if _agent is None:
        # Use cached memory configuration
        memory_config = get_memory_config(actor_id, session_id)
        
        # Create agent with memory session manager
        _agent = Agent(
            model=MODEL_ID,
            session_manager=AgentCoreMemorySessionManager(memory_config, REGION),
            system_prompt=SYSTEM_PROMPT,
            tools=[
                current_time, channel_management, channel_monitoring,
                schedule_management, code_mode, channel_health_monitoring
            ]
        )
    
    return _agent

@app.entrypoint
async def invoke(payload, context):
    """AgentCore Runtime entry point with streaming support"""
    actor_id = context.request_headers.get('X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id', 'user') if context.request_headers else 'user'
    session_id = context.session_id or 'default_session'
    
    try:
        agent = get_or_create_agent(actor_id, session_id)
        
        prompt = payload.get("prompt", "Hello!")
        stream = payload.get("stream", False)
        
        if stream:
            async for event in agent.stream_async(prompt):
                yield event
            metrics_event = build_metrics_event(agent)
            if metrics_event:
                yield metrics_event
        else:
            result = agent(prompt)
            yield {
                "response": result.message.get('content', [{}])[0].get('text', str(result))
            }
    except Exception as e:
        # If validation error due to tool imbalance, reset global agent
        if "toolResult blocks" in str(e) and "toolUse blocks" in str(e):
            global _agent
            _agent = None  # Reset global agent to force recreation
            
            # Create fresh agent
            agent = get_or_create_agent(actor_id, session_id)
            
            if stream:
                async for event in agent.stream_async(prompt):
                    yield event
                metrics_event = build_metrics_event(agent)
                if metrics_event:
                    yield metrics_event
            else:
                result = agent(prompt)
                yield {
                    "response": result.message.get('content', [{}])[0].get('text', str(result))
                }
        else:
            raise

if __name__ == "__main__":
    app.run()
