"""EML specialist LangGraph agent.

Uses langgraph.prebuilt.create_react_agent (ReAct loop with tools + checkpointing).
Reference: langchain-ai/langchain-aws samples/tools/bedrock_agentcore_code_interpreter.ipynb
"""

from langgraph.prebuilt import create_react_agent
from langchain.chat_models import init_chat_model
from langgraph_checkpoint_aws import AgentCoreMemorySaver

from shared.config import Settings
from eml.tools import ALL_TOOLS
from eml.prompts import SYSTEM_PROMPT


_code_toolkit = None


async def _get_code_interpreter_tools(region: str):
    """Lazy-load Code Interpreter toolkit on first use.
    # TODO: wire into build_eml_graph when async init is supported
    """
    global _code_toolkit
    if _code_toolkit is None:
        try:
            from langchain_aws.tools import create_code_interpreter_toolkit
            _code_toolkit, tools = await create_code_interpreter_toolkit(region=region)
        except Exception:
            _code_toolkit = []
            return []
    if isinstance(_code_toolkit, list):
        return _code_toolkit
    return _code_toolkit.get_tools()


def build_eml_graph(checkpointer: AgentCoreMemorySaver):
    """Build the EML specialist agent with ReAct tool loop."""
    settings = Settings()

    model = init_chat_model(
        settings.agent_model_id,
        model_provider="bedrock_converse",
        region_name=settings.region,
    )

    return create_react_agent(
        model,
        tools=list(ALL_TOOLS),
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


async def cleanup_code_interpreter():
    """Clean up Code Interpreter sessions. Call on container shutdown."""
    global _code_toolkit
    if _code_toolkit is not None:
        await _code_toolkit.cleanup()
        _code_toolkit = None
