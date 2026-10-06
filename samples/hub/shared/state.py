"""Shared state schemas for LangGraph agents."""

from typing import TypedDict, Annotated, Literal, Optional
from langgraph.graph import MessagesState
from operator import add


class TodoItem(TypedDict):
    """A single task in the coordinator's execution plan (write_todos pattern)."""
    task_id: str
    description: str
    target_agent: Literal["eml", "emx"]
    priority: int
    depends_on: list[str]
    status: Literal["pending", "in_progress", "completed", "failed"]
    result: Optional[str]


def merge_todos(existing: list[TodoItem], updates: list[TodoItem]) -> list[TodoItem]:
    """Merge todos by task_id — updates replace existing entries."""
    by_id = {t["task_id"]: t for t in existing}
    for t in updates:
        by_id[t["task_id"]] = t
    return list(by_id.values())


class CoordinatorState(MessagesState):
    """State for the coordinator graph."""
    classification: dict
    todos: Annotated[list[TodoItem], merge_todos]
    requires_approval: bool
    approval_status: Literal["pending", "approved", "rejected", "not_required"]
    agent_results: Annotated[list[dict], add]
    session_id: str
    trace_id: str


class SpecialistState(MessagesState):
    """State for EML/EMX specialist graphs."""
    task: dict
    session_id: str
    actor_id: str
