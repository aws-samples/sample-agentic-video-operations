"""EML AgentCore Runtime entrypoint.

Reference: langchain-ai/langchain-aws samples/memory/agentcore_memory_checkpointer.ipynb
"""

import json
from uuid import uuid4

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from shared.memory import create_checkpointer, build_config
from shared.config import Settings
from eml.graph import build_eml_graph

app = BedrockAgentCoreApp()

_settings = Settings()
_checkpointer = create_checkpointer(_settings.memory_id, _settings.region)
_graph = build_eml_graph(_checkpointer)


@app.entrypoint
async def invoke(payload, context):
    """AgentCore Runtime entry point for EML specialist."""

    prompt = payload.get("prompt", "")
    task_id = payload.get("task_id", str(uuid4()))
    session_id = context.session_id or f"eml-{uuid4()}"

    config = build_config("eml", task_id, f"task-{task_id}")

    result = await _graph.ainvoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
    )

    response_text = result["messages"][-1].content
    yield json.dumps({"data": response_text}) + "\n"


if __name__ == "__main__":
    app.run()
