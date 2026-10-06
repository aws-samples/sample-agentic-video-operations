"""Dispatch pending tasks to EML/EMX specialist runtimes."""

import os
from shared.observability import traced_node, trace_delegation
from shared.runtime_client import AgentCoreRuntimeClient
from shared.config import Settings


@traced_node("coordinator.route", "coordinator", "router")
def route_node(state: dict) -> dict:
    """Dispatch ready todos to their target agents."""
    settings = Settings()
    client = AgentCoreRuntimeClient(region=settings.region)

    runtime_map = {
        "eml": settings.eml_runtime_arn,
        "emx": settings.emx_runtime_arn,
    }

    completed_ids = {
        t["task_id"] for t in state.get("todos", [])
        if t["status"] == "completed"
    }

    results = []
    updated_todos = []

    for todo in state.get("todos", []):
        if todo["status"] != "pending":
            updated_todos.append(todo)
            continue

        deps_satisfied = all(d in completed_ids for d in todo.get("depends_on", []))
        if not deps_satisfied:
            updated_todos.append(todo)
            continue

        target = todo["target_agent"]
        runtime_arn = runtime_map.get(target)
        if not runtime_arn:
            updated_todos.append({**todo, "status": "failed", "result": f"Unknown agent: {target}"})
            continue

        with trace_delegation(todo["task_id"], target):
            try:
                response = client.invoke(
                    runtime_arn=runtime_arn,
                    task=todo,
                    session_id=state.get("session_id", "default"),
                )
                updated_todos.append({**todo, "status": "completed", "result": response})
                results.append({
                    "task_id": todo["task_id"],
                    "agent": target,
                    "result": response,
                })
            except Exception as e:
                updated_todos.append({**todo, "status": "failed", "result": str(e)})
                results.append({
                    "task_id": todo["task_id"],
                    "agent": target,
                    "result": f"Error: {e}",
                })

    return {"todos": updated_todos, "agent_results": results}
