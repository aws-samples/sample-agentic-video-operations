"""Merge results and determine if more routing is needed."""

from shared.observability import traced_node


@traced_node("coordinator.merge", "coordinator", "merger")
def merge_node(state: dict) -> dict:
    """Check if all todos are complete or if more routing is needed."""
    return {}


def merge_router(state: dict) -> str:
    """Return 'all_complete' if no pending todos remain, else 'pending'."""
    todos = state.get("todos", [])
    pending = [t for t in todos if t["status"] == "pending"]
    if pending:
        return "pending"
    return "all_complete"
