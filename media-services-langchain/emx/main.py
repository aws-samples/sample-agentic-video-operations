"""EMX AgentCore Runtime entrypoint.

Reference: langchain-ai/langchain-aws samples/memory/agentcore_memory_checkpointer.ipynb
"""

import json
from uuid import uuid4

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from shared.memory import create_checkpointer, build_config
from shared.config import Settings
from emx.graph import build_emx_graph

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    """AgentCore Runtime entry point for EMX specialist."""
    settings = Settings()
    checkpointer = create_checkpointer(settings.memory_id, settings.region)
    graph = build_emx_graph(checkpointer)

    prompt = payload.get("prompt", "")
    task_id = payload.get("task_id", str(uuid4()))
    session_id = context.session_id or f"emx-{uuid4()}"

    config = build_config("emx", task_id, f"task-{task_id}")

    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
    )

    response_text = result["messages"][-1].content
    yield json.dumps({"data": response_text}) + "\n"


if __name__ == "__main__":
    app.run()
