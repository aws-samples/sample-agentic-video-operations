"""EMX specialist LangGraph state machine.

Uses langchain.agents.create_agent (ReAct loop with tools + checkpointing).
Reference: langchain-ai/langchain-aws samples/tools/bedrock_agentcore_code_interpreter.ipynb
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph_checkpoint_aws import AgentCoreMemorySaver

from shared.config import Settings
from emx.tools import ALL_TOOLS
from emx.prompts import SYSTEM_PROMPT


_code_toolkit = None


async def _get_code_interpreter_tools(region: str):
    """Lazy-load Code Interpreter toolkit on first use."""
    global _code_toolkit
    if _code_toolkit is None:
        try:
            from langchain_aws.tools import create_code_interpreter_toolkit
            _code_toolkit, tools = await create_code_interpreter_toolkit(region=region)
            return tools
        except Exception:
            return []
    return []


def build_emx_graph(checkpointer: AgentCoreMemorySaver):
    """Build the EMX specialist agent with ReAct tool loop."""
    settings = Settings()

    model = init_chat_model(
        settings.agent_model_id,
        model_provider="bedrock_converse",
        region_name=settings.region,
    )

    return create_agent(
        model,
        tools=list(ALL_TOOLS),
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


async def cleanup_code_interpreter():
    """Clean up Code Interpreter sessions. Call on container shutdown."""
    global _code_toolkit
    if _code_toolkit is not None:
        await _code_toolkit.cleanup()
        _code_toolkit = None
