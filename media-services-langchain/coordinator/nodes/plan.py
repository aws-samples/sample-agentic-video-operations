"""write_todos deep agent — decomposes complex goals into structured tasks."""

import json
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage
from shared.observability import traced_node
from shared.config import Settings
from coordinator.prompts import PLAN_PROMPT


@traced_node("coordinator.plan", "coordinator", "planner")
def plan_node(state: dict) -> dict:
    """Generate a task breakdown using the write_todos pattern."""
    settings = Settings()
    llm = init_chat_model(
        settings.agent_model_id,
        model_provider="bedrock_converse",
        region_name=settings.region,
    )

    classification = state["classification"]
    user_message = state["messages"][-1].content

    response = llm.invoke([
        SystemMessage(content=PLAN_PROMPT),
        HumanMessage(
            content=f"Classification: {json.dumps(classification)}\n\n"
                    f"User request: {user_message}"
        ),
    ])

    try:
        raw_todos = json.loads(response.content)
    except json.JSONDecodeError:
        raw_todos = [{
            "task_id": "task-1",
            "description": user_message,
            "target_agent": classification.get("domain", "eml"),
            "priority": 1,
            "depends_on": [],
        }]

    todos = [
        {**t, "status": "pending", "result": None}
        for t in raw_todos
    ]

    is_destructive = classification.get("is_destructive", False) or any(
        keyword in t.get("description", "").lower()
        for t in todos
        for keyword in ("start", "stop", "switch", "delete", "restart")
    )

    return {
        "todos": todos,
        "requires_approval": is_destructive,
        "approval_status": "pending" if is_destructive else "not_required",
    }
