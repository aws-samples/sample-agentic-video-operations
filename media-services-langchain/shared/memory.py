"""AgentCore Memory integration for LangGraph checkpointing.

Memory Namespace Strategy:
--------------------------
All three runtimes share a SINGLE CfnMemory resource.
Isolation is achieved through distinct actor_id patterns:

| Runtime     | actor_id pattern          | thread_id        |
|-------------|--------------------------|------------------|
| Coordinator | coordinator-{user_id}    | session-{uuid}   |
| EML         | eml-{task_id}            | task-{uuid}      |
| EMX         | emx-{task_id}            | task-{uuid}      |

This ensures memory is never mixed across agents while keeping
infrastructure simple (one CfnMemory, one set of IAM permissions).
"""

import os
from langgraph_checkpoint_aws import AgentCoreMemorySaver


def create_checkpointer(
    memory_id: str | None = None,
    region: str | None = None,
) -> AgentCoreMemorySaver:
    """Create an AgentCoreMemorySaver instance.

    Args:
        memory_id: AgentCore Memory ID. Defaults to MEMORY_ID env var.
        region: AWS region. Defaults to AWS_REGION env var.

    Reference: langchain-ai/langchain-aws samples/memory/agentcore_memory_checkpointer.ipynb
    """
    memory_id = memory_id or os.getenv("MEMORY_ID", "")
    region = region or os.getenv("AWS_REGION", "us-west-2")

    return AgentCoreMemorySaver(memory_id, region_name=region)


def build_config(agent_prefix: str, identifier: str, session_id: str) -> dict:
    """Build LangGraph config with proper namespace isolation.

    Args:
        agent_prefix: One of 'coordinator', 'eml', 'emx'
        identifier: user_id for coordinator, task_id for specialists
        session_id: Session or task UUID
    """
    return {
        "configurable": {
            "thread_id": session_id,
            "actor_id": f"{agent_prefix}-{identifier}",
        }
    }
