"""Approval gate for destructive operations using LangGraph interrupt."""

from langgraph.types import interrupt
from shared.observability import traced_node


@traced_node("coordinator.approve", "coordinator", "approver")
def approve_node(state: dict) -> dict:
    """Gate destructive operations. Auto-approves read-only tasks."""
    if not state.get("requires_approval", False):
        return {"approval_status": "not_required"}

    approval = interrupt({
        "action": "approve_plan",
        "message": "The following plan includes destructive operations. Approve?",
        "todos": state["todos"],
    })

    if approval.get("approved", False):
        return {"approval_status": "approved"}
    return {"approval_status": "rejected"}


def approval_router(state: dict) -> str:
    """Route based on approval status."""
    status = state.get("approval_status", "not_required")
    if status in ("approved", "not_required"):
        return "approved"
    return "rejected"
